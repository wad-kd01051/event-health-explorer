"""
로그 설계서(Google Sheets) 연동

gspread + google-auth 사용.
실제 이벤트 사용 현황과 설계서 정의를 비교해서
- 설계서에 있지만 실제 발생 없음 → Dead 후보
- 실제 발생하지만 설계서에 없음 → 미정의 이벤트
를 탐지.
"""
from __future__ import annotations

import html
import io
import json
import re
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import pandas as pd


# ──────────────────────────────────────────────────────────────
# xlsx 전체를 받아 openpyxl 로 파싱 — gviz CSV 의 탭 정확도 이슈 회피
# ──────────────────────────────────────────────────────────────
_XML_ILLEGAL_CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _fetch_workbook(spreadsheet_url: str):
    """xlsx 다운로드 + 불법 제어문자 sanitize 후 openpyxl workbook 반환."""
    import openpyxl

    sid = _extract_sheet_id(spreadsheet_url)
    xlsx_url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    with urllib.request.urlopen(xlsx_url) as r:
        raw = r.read()

    src = io.BytesIO(raw)
    dst = io.BytesIO()
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            body = zi.read(info.filename)
            if info.filename.endswith((".xml", ".rels")):
                body = _XML_ILLEGAL_CTRL.sub(b"", body)
            zo.writestr(info, body)
    dst.seek(0)
    return openpyxl.load_workbook(dst, data_only=True, read_only=True)


def _sheet_to_dataframe(ws) -> pd.DataFrame:
    """openpyxl worksheet → header=None 방식 DataFrame."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return pd.DataFrame()
    # None → NaN 변환을 위해 DataFrame 생성
    max_cols = max((len(r) for r in rows), default=0)
    padded = [list(r) + [None] * (max_cols - len(r)) for r in rows]
    df = pd.DataFrame(padded)
    # 문자열 dtype 로 통일
    return df.astype(object)


# ──────────────────────────────────────────────────────────────
# 카테고리(=탭) 기반 이벤트 목록 추출
# ──────────────────────────────────────────────────────────────
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
# 카테고리로 분류할 탭 패턴: 숫자 접두어로 시작 (예: "03. 메인_신규로그설계")
_CATEGORY_TAB_RE = re.compile(r"^\d+\.\s")


def _extract_sheet_id(spreadsheet_url: str) -> str:
    m = _SHEET_ID_RE.search(spreadsheet_url)
    if not m:
        raise ValueError("올바른 Google Sheets URL 이 아닙니다.")
    return m.group(1)


def list_category_tabs(spreadsheet_url: str) -> List[str]:
    """
    xlsx export 로 전체 workbook 메타만 받아 visible 한 카테고리 탭 이름을 반환.
    `"03. 메인_신규로그설계"` 처럼 숫자 접두어가 있는 탭만 카테고리로 간주.
    """
    sid = _extract_sheet_id(spreadsheet_url)
    xlsx_url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    with urllib.request.urlopen(xlsx_url) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("xl/workbook.xml").decode("utf-8", errors="ignore")

    pat = re.compile(
        r'<sheet\s+(?:state="(\w+)"\s+)?name="([^"]+)"\s+sheetId="\d+"'
    )
    tabs: List[str] = []
    for state, name in pat.findall(xml):
        visible = state == "" or state == "visible"
        if not visible:
            continue
        name = html.unescape(name)
        if _CATEGORY_TAB_RE.match(name):
            tabs.append(name)
    return tabs


_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,59}$")
# 헤더 — "eventName", "event_name", "eventName(Amplitude)", "eventName(GA)", "eventName.1" 등
_EVENT_NAME_HEADER_RE = re.compile(
    r"^event\s*_?\s*name\s*(\([^)]*\))?\s*(\.\d+)?$", re.IGNORECASE
)
_AMPLITUDE_LABEL_RE = re.compile(r"amplitude", re.IGNORECASE)
_GA4_LABEL_RE = re.compile(r"\bga4?\b|google", re.IGNORECASE)


def _classify_header_label(label: str) -> Optional[str]:
    """헤더 텍스트의 (Amplitude) / (GA) 힌트로 소스 판별."""
    if _AMPLITUDE_LABEL_RE.search(label):
        return "amplitude"
    if _GA4_LABEL_RE.search(label):
        return "ga4"
    return None


def _is_valid_event_name(s: str) -> bool:
    """실제 이벤트명 패턴만 허용 — 공백/한글/특수문자 있는 메타는 제외."""
    if not s or len(s) > 60:
        return False
    low = s.strip().lower()
    if low in {"nan", "none", "eventname", "event_name"}:
        return False
    return bool(_EVENT_NAME_RE.match(s))


def _matches_source_convention(name: str, source: str) -> bool:
    """네이밍 컨벤션으로 소스 일치 여부 판별.
    - Amplitude: double underscore `__` 포함 (예: `impr__item`, `click__confirm`)
    - GA4:       single underscore 만 (예: `main_topGNB_searchInput_click`)
    """
    has_dbl = "__" in name
    return has_dbl if source == "amplitude" else not has_dbl


def _find_event_name_columns(
    df_raw: pd.DataFrame, max_header_rows: int = 10
) -> List[Tuple[int, str]]:
    """앞 N 행에서 eventName 계열 셀 위치를 `(col_idx, label)` 튜플로 반환."""
    seen: Dict[int, str] = {}
    for row_idx in range(min(max_header_rows, len(df_raw))):
        for col_idx in range(df_raw.shape[1]):
            val = df_raw.iat[row_idx, col_idx]
            if pd.isna(val):
                continue
            s = str(val).strip()
            if _EVENT_NAME_HEADER_RE.match(s):
                if col_idx not in seen:
                    seen[col_idx] = s
    return sorted(seen.items())


def _pick_source_columns(
    cols_with_label: List[Tuple[int, str]], source: str
) -> List[int]:
    """힌트 우선, 없으면 위치 기반으로 소스별 대상 컬럼 인덱스 리스트 반환."""
    hinted = [c for c, l in cols_with_label if _classify_header_label(l) == source]
    if hinted:
        return hinted
    # fallback — 힌트 없는 컬럼들 중 위치 기반
    unhinted = [c for c, l in cols_with_label if _classify_header_label(l) is None]
    return unhinted[:1] if source == "amplitude" else unhinted[1:]


# 하위 호환용 — 기존 호출부가 쓸 수 있음
def _find_event_name_col_indices(df_raw, max_header_rows=10):
    return [c for c, _ in _find_event_name_columns(df_raw, max_header_rows)]


def load_event_details(
    spreadsheet_url: str,
    tab_names: List[str],
    source: str = "amplitude",
) -> pd.DataFrame:
    """
    이벤트별 전체 행 데이터를 DataFrame 으로 반환.
    컬럼에 `_event_name`, `_category` 추가. 나머지는 설계서 원본 컬럼 그대로.
    """
    rows: List[dict] = []

    try:
        wb = _fetch_workbook(spreadsheet_url)
    except Exception:
        return pd.DataFrame()

    tab_set = set(tab_names)
    for ws in wb.worksheets:
        if ws.title not in tab_set:
            continue
        df = _sheet_to_dataframe(ws)
        if df.empty:
            continue
        tab = ws.title

        cols_with_label = _find_event_name_columns(df)
        if not cols_with_label:
            continue

        en_col_idxs = [c for c, _ in cols_with_label]
        # 헤더 행 위치 탐지 (eventName 이 등장한 row 중 첫 번째)
        header_row = 0
        for r in range(min(10, len(df))):
            if any(
                pd.notna(df.iat[r, c]) and _EVENT_NAME_HEADER_RE.match(str(df.iat[r, c]).strip())
                for c in en_col_idxs
            ):
                header_row = r
                break

        col_names = {}
        for c in range(df.shape[1]):
            hv = df.iat[header_row, c] if header_row < len(df) else None
            col_names[c] = str(hv).strip() if pd.notna(hv) else f"col_{c}"

        target_idxs = _pick_source_columns(cols_with_label, source)

        for i in range(header_row + 1, len(df)):
            for idx in target_idxs:
                ev = df.iat[i, idx]
                if pd.isna(ev):
                    continue
                ev = str(ev).replace("$", "").strip()
                if ev.endswith("_") or not _is_valid_event_name(ev):
                    continue
                if not _matches_source_convention(ev, source):
                    continue
                row_data = {col_names[c]: df.iat[i, c] for c in range(df.shape[1])}
                row_data["_event_name"] = ev
                row_data["_category"] = tab
                rows.append(row_data)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_events_by_category(
    spreadsheet_url: str,
    tab_names: List[str],
    source: str = "amplitude",
) -> Tuple[Set[str], Dict[str, List[str]]]:
    """
    설계서 카테고리 탭들에서 해당 소스의 이벤트명 집합 + 이벤트→카테고리 매핑 반환.

    탭마다 컬럼 위치가 달라서 "eventName 계열 헤더 + 네이밍 컨벤션" 조합으로 탐지:
      1) `eventName`/`event_name`/`eventName.N` 헤더 컬럼 전부 수집
      2) 각 값의 `__` 포함 여부로 Amplitude/GA4 판별 (요청 소스와 일치할 때만 포함)
    이러면 탭별 컬럼 순서가 달라도 정확히 분류됨.
    """
    events: Set[str] = set()
    categories_of: Dict[str, List[str]] = {}

    try:
        wb = _fetch_workbook(spreadsheet_url)
    except Exception:
        return events, categories_of

    tab_set = set(tab_names)
    for ws in wb.worksheets:
        if ws.title not in tab_set:
            continue
        df = _sheet_to_dataframe(ws)
        if df.empty:
            continue

        cols_with_label = _find_event_name_columns(df)
        if not cols_with_label:
            continue

        target_idxs = _pick_source_columns(cols_with_label, source)

        for idx in target_idxs:
            for val in df.iloc[:, idx].dropna():
                ev = str(val).replace("$", "").strip()
                if ev.endswith("_"):
                    continue
                if not _is_valid_event_name(ev):
                    continue
                if not _matches_source_convention(ev, source):
                    continue
                events.add(ev)
                categories_of.setdefault(ev, []).append(ws.title)

    return events, categories_of


def load_design_doc(
    spreadsheet_url: str,
    worksheet_name: Optional[str] = None,
    service_account_info: Optional[str] = None,
) -> pd.DataFrame:
    """
    로그 설계서 스프레드시트를 DataFrame으로 로드.

    service_account_info:
        - JSON 문자열 그대로 (환경변수용)
        - 또는 파일 경로
        - 또는 None (시트가 공개 읽기라면 공개 CSV export URL 사용)
    """
    if service_account_info:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        # 파일 경로인지 JSON 문자열인지 판단
        if Path(service_account_info).exists():
            creds = Credentials.from_service_account_file(
                service_account_info, scopes=scopes
            )
        else:
            info = json.loads(service_account_info)
            creds = Credentials.from_service_account_info(info, scopes=scopes)

        gc = gspread.authorize(creds)
        sh = gc.open_by_url(spreadsheet_url)
        ws = sh.worksheet(worksheet_name) if worksheet_name else sh.sheet1

        values = ws.get_all_values()
        if not values:
            return pd.DataFrame()
        df = pd.DataFrame(values[1:], columns=values[0])
        # 빈 컬럼명 제거
        df = df.loc[:, df.columns != ""]
        return df

    # service account 없으면 공개 CSV export 시도
    # URL 패턴: https://docs.google.com/spreadsheets/d/{ID}/edit#gid={GID}
    import re
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_url)
    if not m:
        raise ValueError("올바른 Google Sheets URL이 아닙니다.")
    sheet_id = m.group(1)

    gid_match = re.search(r"gid=(\d+)", spreadsheet_url)
    gid = gid_match.group(1) if gid_match else "0"

    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}"
    )
    return pd.read_csv(csv_url)


def compare_with_actual(
    design_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    design_event_col: str = "event_name",
) -> pd.DataFrame:
    """
    설계서와 실제 이벤트 사용 현황 대조.

    반환 컬럼:
        event_name, in_design, in_actual, health_status,
        events_last_30d, diagnosis
    """
    design_events = set(
        design_df[design_event_col].dropna().astype(str).str.strip().unique()
    )
    actual_events = set(actual_df["event_name"].unique())

    all_events = design_events | actual_events

    rows = []
    for ev in sorted(all_events):
        in_design = ev in design_events
        in_actual = ev in actual_events
        actual_row = actual_df[actual_df["event_name"] == ev]

        status = actual_row["health_status"].iloc[0] if not actual_row.empty else None
        events_30d = (
            int(actual_row["events_last_30d"].iloc[0])
            if not actual_row.empty else 0
        )

        if in_design and not in_actual:
            diagnosis = "⚠️ 설계서에만 있음 — 구현 누락 또는 삭제 필요"
        elif not in_design and in_actual:
            diagnosis = "📝 설계서 미정의 — 문서화 필요"
        elif status == "Dead":
            diagnosis = "⚰️ 양쪽에 있으나 사용 안 됨 — 제거 검토"
        elif status == "Dormant":
            diagnosis = "💤 휴면 — 담당자 확인"
        else:
            diagnosis = "✅ 정상"

        rows.append({
            "event_name": ev,
            "in_design": in_design,
            "in_actual": in_actual,
            "health_status": status,
            "events_last_30d": events_30d,
            "diagnosis": diagnosis,
        })

    return pd.DataFrame(rows)

"""
🩺 Event Health Explorer

GA4 이벤트 사용 현황 조회 웹앱.
- dbt profiles.yml로 Snowflake 자동 연결
- 스키마 동적 탐지 → param 자동 발견
- 로그 설계서(Google Sheets)와 대조
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# src 모듈 import 가능하게
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import SOURCE_SPECS, load_config
from src.event_analyzer import run_daily_trend, run_overview
from src.schema_inspector import detect_ga4_event_name_key, inspect_table
from src.sheets_client import (
    compare_with_actual,
    list_category_tabs,
    load_design_doc,
    load_event_details,
    load_events_by_category,
)
from src.snowflake_client import SnowflakeClient

# ──────────────────────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Event Health Explorer",
    page_icon="🩺",
    layout="wide",
)

STATUS_COLORS = {
    "Active":    "#22c55e",
    "Growing":   "#3b82f6",
    "New":       "#06b6d4",
    "Declining": "#f59e0b",
    "Dormant":   "#a1a1aa",
    "Dead":      "#ef4444",
    "Anomalous": "#a855f7",
}
STATUS_EMOJI = {
    "Active": "✅", "Growing": "📈", "New": "🆕",
    "Declining": "📉", "Dormant": "💤", "Dead": "⚰️", "Anomalous": "⚠️",
}


# ──────────────────────────────────────────────────────────────
# 리소스 초기화 (캐시)
# ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    cfg = load_config()
    return SnowflakeClient(cfg.snowflake), cfg


@st.cache_data(ttl=3600, show_spinner="📐 스키마 탐지 중...")
def get_schema(_client, database, schema, table, source_key):
    return inspect_table(
        _client, database, schema, table,
        source_spec=SOURCE_SPECS[source_key],
    )


def _build_source_spec(source_key: str, event_name_col_override=None):
    """SOURCE_SPECS 복사본에 GA4 탐지된 event_name_col 을 override 적용."""
    spec = dict(SOURCE_SPECS[source_key])
    if event_name_col_override:
        spec["event_name_col"] = event_name_col_override
    return spec


@st.cache_data(ttl=3600, show_spinner="📊 이벤트 건강도 분석 중...")
def get_overview(
    _client, _schema, monitored_params_tuple, lookback, mart_fqn,
    filter_events_tuple, source_key, event_name_col_override=None,
):
    return run_overview(
        _client, _schema, list(monitored_params_tuple), lookback, mart_fqn,
        list(filter_events_tuple),
        source_spec=_build_source_spec(source_key, event_name_col_override),
    )


@st.cache_data(ttl=3600, show_spinner="📈 트렌드 조회 중...")
def get_trend(_client, _schema, event_name, lookback, source_key, event_name_col_override=None):
    return run_daily_trend(
        _client, _schema, event_name, lookback,
        source_spec=_build_source_spec(source_key, event_name_col_override),
    )


@st.cache_data(ttl=3600, show_spinner="🔎 GA4 이벤트명 param key 자동 탐지 중...")
def detect_ga4_key(_client, db, sch, tbl, sample_tuple):
    return detect_ga4_event_name_key(_client, db, sch, tbl, list(sample_tuple))


@st.cache_data(ttl=3600, show_spinner="📋 로그 설계서 로드 중...")
def get_design_doc(url, worksheet, sa_json):
    return load_design_doc(url, worksheet, sa_json)


@st.cache_data(ttl=3600, show_spinner="📂 카테고리 탭 목록 조회 중...")
def get_category_tabs(url):
    return list_category_tabs(url)


@st.cache_data(ttl=3600, show_spinner="📂 선택 카테고리의 이벤트 목록 로드 중...")
def get_events_for_categories(url, tabs_tuple, source_key):
    events, mapping = load_events_by_category(
        url, list(tabs_tuple), source=source_key,
    )
    return events, mapping


@st.cache_data(ttl=3600, show_spinner="📖 이벤트 정의/설명 로드 중...")
def get_event_details(url, tabs_tuple, source_key):
    return load_event_details(url, list(tabs_tuple), source=source_key)


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#666")
    emoji = STATUS_EMOJI.get(status, "")
    return (
        f'<span style="background:{color};color:white;padding:4px 12px;'
        f'border-radius:12px;font-weight:600">{emoji} {status}</span>'
    )


# ──────────────────────────────────────────────────────────────
# 앱 시작
# ──────────────────────────────────────────────────────────────
st.title("🩺 Event Health Explorer")
st.caption("Amplitude 이벤트의 사용 현황을 동적으로 분석합니다")

# 연결
try:
    client, cfg = get_client()
except Exception as e:
    st.error(f"⚠️ Snowflake 연결 설정 오류: {e}")
    st.info(
        "**해결 방법**\n\n"
        "프로젝트 루트에 `.env` 파일을 만들고 다음을 입력하세요:\n"
        "```\n"
        "DBT_SNOWFLAKE_ACCOUNT=BVJAEKO-LA86305\n"
        "DBT_SNOWFLAKE_USER=본인이메일@catchtable.co.kr\n"
        "DBT_TARGET=dev\n"
        "```\n"
        "인증은 **SSO (브라우저)** 로 자동 동작합니다."
    )
    st.stop()

# SiS가 아니고 SSO 인증일 때만 브라우저 팝업 안내
if not client.is_sis and cfg.snowflake.authenticator == "externalbrowser":
    st.toast("🌐 SSO 인증: 첫 쿼리 시 브라우저 팝업이 뜨면 로그인해주세요", icon="🔐")

# ──────────────────────────────────────────────────────────────
# 사이드바: 설정 및 스키마 제어
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    # 데이터 소스 선택
    source_key = st.radio(
        "🎯 데이터 소스",
        options=list(SOURCE_SPECS.keys()),
        format_func=lambda k: SOURCE_SPECS[k]["label"],
        horizontal=True,
        key="source_key",
    )
    source_spec = SOURCE_SPECS[source_key]
    _src_table = cfg.snowflake.get_source_table(source_key)

    with st.expander("🗂️ 원본 테이블", expanded=False):
        events_db = st.text_input(
            "Database", value=_src_table.database if _src_table else "",
            key=f"db_{source_key}",
        )
        events_schema = st.text_input(
            "Schema", value=_src_table.schema if _src_table else "",
            key=f"sch_{source_key}",
        )
        events_table = st.text_input(
            "Table", value=_src_table.table if _src_table else "",
            key=f"tbl_{source_key}",
        )


    lookback_days = st.slider(
        "조회 기간 (일)", 60, 365, 90, step=30,
        help="증감률은 최근 30일 vs 31~60일 전 비교 — 최소 60일 필요",
    )
    mart_fqn = cfg.snowflake.resolve_mart_fqn()
    if mart_fqn:
        st.caption(f"⚡ mart 사용 중: `{mart_fqn}`")
    else:
        st.caption("⚠️ mart 미설정 — raw 직접 조회 (길게 잡으면 느림)")

    if st.button("🔄 캐시 초기화 / 재탐지"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(f"마지막 조회: {datetime.now():%Y-%m-%d %H:%M}")
    if client.is_sis:
        st.caption("🧊 Streamlit in Snowflake (활성 세션 사용)")
    else:
        st.caption(f"👤 `{cfg.snowflake.user}`")
        st.caption(f"🏢 `{cfg.snowflake.account}` / target=`{os.getenv('DBT_TARGET', 'dev')}`")
        auth_display = "🔐 SSO (externalbrowser)" if cfg.snowflake.authenticator == "externalbrowser" else "🔑 " + (cfg.snowflake.authenticator or "password")
        st.caption(f"인증: {auth_display}")
        st.caption(f"🏭 WH `{cfg.snowflake.warehouse}`")

    with st.expander("ℹ️ 건강 상태 분류 기준"):
        st.markdown("""
        - **Active**: 정상 운영 중
        - **Growing**: 볼륨 +50% 이상 증가
        - **Declining**: -50% 이상 감소
        - **Dormant**: 30일 이상 발생 없음
        - **Dead**: 90일 이상 발생 없음
        - **Anomalous**: 비정상 급변 (>300%)
        """)

# ──────────────────────────────────────────────────────────────
# 스키마 탐지
# ──────────────────────────────────────────────────────────────
try:
    schema = get_schema(client, events_db, events_schema, events_table, source_key)
except Exception as e:
    st.error(f"스키마 탐지 실패: {e}")
    st.stop()

st.success(
    f"✅ 스키마 탐지 완료: **{schema.fqn}** "
    f"/ 컬럼 {len(schema.columns)}개 "
    f"/ 발견된 param 키 {len(schema.flattened_param_keys)}개"
)

# 모니터링할 param 선택 UI
with st.sidebar:
    st.divider()
    st.subheader("📊 null rate 모니터링 대상")
    default_params = [
        k for k in ["pageName", "actionName", "objectType", "screen_name", "screenName"]
        if k in schema.flattened_param_keys
    ][:3]
    monitored_params = st.multiselect(
        "EVENT_PROPERTIES 키",
        options=schema.flattened_param_keys,
        default=default_params,
        help="선택된 param들의 null 비율을 건강도에 반영합니다",
    )


# ──────────────────────────────────────────────────────────────
# 🔎 분석 범위 선택 (카테고리 → 이벤트 → 실행)
# ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("🔎 분석 범위 선택")
st.caption("선택한 이벤트만 Snowflake 에 조회되어 비용을 최소화합니다.")

if not cfg.sheets.spreadsheet_url:
    st.error("⚠️ 설계서 URL이 없습니다. `.env` 의 `SHEETS_URL` 을 설정하세요.")
    st.stop()

try:
    all_tabs = get_category_tabs(cfg.sheets.spreadsheet_url)
except Exception as e:
    st.error(f"설계서 카테고리 탭 조회 실패: {e}")
    st.stop()

col_cat, col_ev = st.columns([2, 3])
with col_cat:
    selected_cats = st.multiselect(
        "📂 카테고리",
        options=all_tabs,
        default=[],
        help=f"전체 {len(all_tabs)}개 카테고리 중 선택",
    )

selected_events: list = []
event_category_map: dict = {}
if selected_cats:
    try:
        events, event_category_map = get_events_for_categories(
            cfg.sheets.spreadsheet_url, tuple(selected_cats), source_key
        )
    except Exception as e:
        st.error(f"카테고리 이벤트 로드 실패: {e}")
        st.stop()
    available_events = sorted(events)
    with col_ev:
        selected_events = st.multiselect(
            f"📌 이벤트 ({len(available_events):,}개 중)",
            options=available_events,
            default=[],
            help="하나 또는 여러 개 선택 — 입력창에 타이핑하면 필터됨",
        )
        st.caption(
            f"선택됨: **{len(selected_events)}**개"
            + (f" / 표시 {len(available_events):,}개" if available_events else "")
        )
else:
    with col_ev:
        st.caption("← 먼저 카테고리를 선택하세요")

run_clicked = st.button(
    "🔍 분석 실행",
    type="primary",
    disabled=not selected_events,
    use_container_width=True,
)

if run_clicked:
    st.session_state["queried_events"] = tuple(selected_events)
    st.session_state["event_category_map"] = event_category_map

queried_events = st.session_state.get("queried_events")
if not queried_events:
    st.info("👆 카테고리 → 이벤트 선택 후 **🔍 분석 실행** 클릭")
    st.stop()

st.divider()

# GA4 override 불필요 — EVENT_NAME 컬럼에 이벤트명이 직접 들어있음
event_name_override = None

# ──────────────────────────────────────────────────────────────
# 선택 이벤트만 Snowflake 조회
# ──────────────────────────────────────────────────────────────
try:
    df_all = get_overview(
        client, schema, tuple(monitored_params), lookback_days, mart_fqn,
        queried_events, source_key, event_name_override,
    )
except Exception as e:
    st.error(f"분석 쿼리 실행 실패: {e}")
    with st.expander("상세 오류"):
        st.exception(e)
    st.stop()

if df_all.empty:
    st.warning(
        f"선택한 {len(queried_events)}개 이벤트 중 최근 {lookback_days}일간 "
        "발생한 건이 없습니다."
    )
    st.stop()

# JOIN으로 컬럼이 중복됐을 수 있어 안전하게 제거
df_all = df_all.loc[:, ~df_all.columns.duplicated()].copy()

# 카테고리 매핑 컬럼 (탭2 목록에 표시)
mapping = st.session_state.get("event_category_map", {})
if mapping:
    df_all["categories"] = df_all["event_name"].map(
        lambda ev: ", ".join(mapping.get(ev, []))
    )

st.caption(
    f"✅ 조회 완료: 선택 이벤트 **{len(queried_events):,}개** 중 "
    f"{lookback_days}일 내 발생 **{len(df_all):,}개**"
)

# KPI 카드
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("총 이벤트 종류", f"{len(df_all):,}")
c2.metric("✅ Active",    int((df_all.health_status == "Active").sum()))
c3.metric("📉 Declining", int((df_all.health_status == "Declining").sum()))
c4.metric("💤 Dormant",   int((df_all.health_status == "Dormant").sum()))
c5.metric("⚰️ Dead",      int((df_all.health_status == "Dead").sum()))

st.divider()

# ──────────────────────────────────────────────────────────────
# 탭
# ──────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 이벤트 검색",
    "📊 건강 상태별 목록",
    "📋 설계서 대조",
    "📖 이벤트 정의",
])

# ─── 탭 1 ─────────────────────────────────────────────────────
with tab1:
    st.subheader("이벤트 검색")
    event_list = sorted(df_all["event_name"].unique().tolist())
    selected = st.selectbox(
        "이벤트 선택 / 검색",
        options=[""] + event_list,
        placeholder="예: page_view, purchase, ...",
    )

    if selected:
        row = df_all[df_all["event_name"] == selected].iloc[0]

        ca, cb = st.columns([1, 3])
        with ca:
            st.markdown(f"### `{selected}`")
            st.markdown(status_badge(row["health_status"]), unsafe_allow_html=True)
        with cb:
            st.info(f"**권고**: {row['recommendation']}")

        st.divider()

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric(f"{lookback_days}일 발생", f"{int(row['total_events_180d']):,}")
        m2.metric("30일 발생", f"{int(row['events_last_30d']):,}")
        m3.metric("30일 UU", f"{int(row['users_last_30d']):,}")
        change = row["volume_change_pct"]
        if pd.notna(change):
            change_display = f"{change:+.1f}%"
        elif row.get("health_status") == "New":
            change_display = "🆕 NEW"
        else:
            change_display = "N/A"
        m4.metric("증감률", change_display)
        m5.metric("마지막 발생", str(row["last_seen_date"]))
        m6.metric("미발생 일수", f"{int(row['days_since_last_event'])}일")

        st.divider()

        # 일별 트렌드
        st.subheader(f"{lookback_days}일 일별 추이")
        df_trend = get_trend(
            client, schema, selected, lookback_days, source_key,
            event_name_override,
        )
        if not df_trend.empty:
            fig = px.line(
                df_trend,
                x="event_date",
                y=["event_count", "unique_users"],
                labels={"value": "건수", "event_date": "날짜", "variable": "지표"},
            )
            fig.update_layout(height=380, hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

        # null rate
        null_cols = [c for c in row.index if c.startswith("null_rate_")]
        if null_cols:
            st.subheader("주요 파라미터 누락률")
            cols = st.columns(len(null_cols))
            for col, nc in zip(cols, null_cols):
                val = row[nc]
                col.metric(
                    nc.replace("null_rate_", "").replace("_", " "),
                    f"{val:.1f}%" if pd.notna(val) else "N/A",
                )

        with st.expander("📋 전체 지표 원본"):
            st.dataframe(row.to_frame().T, use_container_width=True)
    else:
        st.info("👆 위 검색창에서 이벤트를 선택하세요.")

# ─── 탭 2 ─────────────────────────────────────────────────────
with tab2:
    st.subheader("건강 상태별 이벤트 목록")

    col_chart, col_filter = st.columns([1, 2])
    with col_chart:
        counts = df_all["health_status"].value_counts().reset_index()
        counts.columns = ["health_status", "count"]
        fig = px.pie(
            counts, values="count", names="health_status",
            hole=0.5, color="health_status",
            color_discrete_map=STATUS_COLORS,
        )
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    with col_filter:
        statuses = st.multiselect(
            "건강 상태 필터",
            options=list(STATUS_COLORS.keys()),
            default=["Dead", "Dormant"],
        )
        sort_by = st.selectbox(
            "정렬",
            ["total_events_180d", "events_last_30d",
             "days_since_last_event", "volume_change_pct"],
        )

    df_f = df_all[df_all["health_status"].isin(statuses)] if statuses else df_all
    df_f = df_f.sort_values(sort_by, ascending=False)

    st.caption(f"조회 결과: **{len(df_f):,}건**")

    display_cols = ["event_name", "health_status", "last_seen_date",
                    "days_since_last_event", "events_last_30d",
                    "users_last_30d", "volume_change_pct", "recommendation"]
    if "categories" in df_f.columns:
        display_cols.insert(1, "categories")
    st.dataframe(df_f[display_cols], use_container_width=True, hide_index=True)

    csv = df_f.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드",
        csv,
        f"event_health_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )

# ─── 탭 3: 설계서 대조 ───────────────────────────────────────
with tab3:
    st.subheader("로그 설계서 vs 실제 사용 현황")

    default_url = cfg.sheets.spreadsheet_url or ""
    sheet_url = st.text_input(
        "Google Sheets URL",
        value=default_url,
        help="설계서 스프레드시트 URL을 붙여넣으세요",
    )
    worksheet_name = st.text_input(
        "시트 이름 (비우면 첫 번째 시트)",
        value=cfg.sheets.worksheet_name or "",
    )

    if st.button("🔍 대조 실행", disabled=not sheet_url):
        try:
            df_design = get_design_doc(
                sheet_url,
                worksheet_name or None,
                cfg.sheets.service_account_json,
            )
            st.success(f"설계서 로드: {len(df_design)}행")

            # 이벤트명 컬럼 자동 탐지
            ev_col_candidates = [
                c for c in df_design.columns
                if "event" in c.lower() and "name" in c.lower()
            ]
            if not ev_col_candidates:
                ev_col_candidates = [df_design.columns[0]]

            ev_col = st.selectbox("이벤트명 컬럼", ev_col_candidates)

            df_cmp = compare_with_actual(df_design, df_all, ev_col)

            # 요약
            only_design = int(
                ((df_cmp.in_design) & (~df_cmp.in_actual)).sum()
            )
            only_actual = int(
                ((~df_cmp.in_design) & (df_cmp.in_actual)).sum()
            )
            both = int(((df_cmp.in_design) & (df_cmp.in_actual)).sum())

            k1, k2, k3 = st.columns(3)
            k1.metric("설계서에만 있음", only_design, help="구현 누락 또는 삭제 필요")
            k2.metric("실제에만 있음", only_actual, help="설계서 미정의")
            k3.metric("양쪽에 있음", both)

            st.dataframe(df_cmp, use_container_width=True, hide_index=True)

            csv = df_cmp.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📥 대조 결과 CSV",
                csv,
                f"design_vs_actual_{datetime.now():%Y%m%d}.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.error(f"설계서 로드/대조 실패: {e}")
            with st.expander("상세 오류"):
                st.exception(e)

# ─── 탭 4: 이벤트 정의/설명 ─────────────────────────────────
with tab4:
    st.subheader("📖 이벤트 정의 / 설명")
    st.caption("선택한 카테고리(탭)의 설계서 row 전체를 표시합니다.")

    if not selected_cats:
        st.info("사이드바에서 먼저 카테고리를 선택하세요.")
    else:
        try:
            df_defs = get_event_details(
                cfg.sheets.spreadsheet_url, tuple(selected_cats), source_key,
            )
        except Exception as e:
            st.error(f"설계서 상세 로드 실패: {e}")
            df_defs = pd.DataFrame()

        if df_defs.empty:
            st.warning("선택한 카테고리에서 이벤트 정의를 찾지 못했습니다.")
        else:
            # 분석 실행한 이벤트가 있으면 그 안에서만 선택, 없으면 전체
            candidate_events = (
                sorted(set(queried_events) & set(df_defs["_event_name"]))
                if queried_events else
                sorted(df_defs["_event_name"].unique())
            )
            if not candidate_events:
                candidate_events = sorted(df_defs["_event_name"].unique())

            def_event = st.selectbox(
                f"📌 이벤트 ({len(candidate_events):,}개)",
                options=candidate_events,
                key="def_event_select",
            )

            if def_event:
                matched = df_defs[df_defs["_event_name"] == def_event]
                for i, (_, row) in enumerate(matched.iterrows()):
                    cat = row.get("_category", "-")
                    with st.expander(
                        f"📂 {cat}", expanded=(i == 0)
                    ):
                        # 설계서 원본 컬럼 key-value 나열
                        hidden_prefix = ("_", "Unnamed")
                        for col, val in row.items():
                            if any(col.startswith(p) for p in hidden_prefix):
                                continue
                            if pd.isna(val):
                                continue
                            sval = str(val).strip()
                            if not sval or sval.lower() in {"nan", "none"}:
                                continue
                            st.markdown(f"**{col}**")
                            st.write(sval)

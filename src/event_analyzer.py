"""
이벤트 건강도 분석

View를 만들지 않고 매번 동적으로 SQL 생성/실행.
탐지된 스키마에 맞춰 null rate 체크 대상 param을 자동 선택.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.schema_inspector import TableSchema
from src.snowflake_client import SnowflakeClient


# ──────────────────────────────────────────────────────────────
# 건강 상태 분류 기준
# ──────────────────────────────────────────────────────────────
def classify_health(
    days_since_last: int,
    volume_change_rate: Optional[float],
    events_last_30d: int = 0,
    events_prev_30d: int = 0,
) -> tuple[str, str]:
    """(health_status, recommendation) 반환"""
    if days_since_last >= 90:
        return "Dead", "스토리지/설계서에서 제거 검토"
    if days_since_last >= 30:
        return "Dormant", "담당자에게 사용 여부 확인"
    # 신규: 최근 30일엔 발생했지만 그 이전 30일 (31~60일 전) 엔 없음
    if events_last_30d > 0 and events_prev_30d == 0:
        return "New", "최근 출시/부활 — 추세 추적 시작"
    if volume_change_rate is not None and abs(volume_change_rate) > 3.0:
        return "Anomalous", "중복 발화/루프 여부 점검"
    if volume_change_rate is not None and volume_change_rate > 0.5:
        return "Growing", "트래픽 증가 확인"
    if volume_change_rate is not None and volume_change_rate < -0.5:
        return "Declining", "볼륨 급감 원인 조사"
    return "Active", "정상 운영"


# ──────────────────────────────────────────────────────────────
# SQL 빌더
# ──────────────────────────────────────────────────────────────
def _events_in_clause(event_names: Optional[List[str]], event_name_col: str = "EVENT_TYPE") -> str:
    """{event_name_col} IN (...) WHERE 조각. 없으면 빈 문자열."""
    if not event_names:
        return ""
    quoted = ",".join(f"'{e.replace(chr(39), chr(39)*2)}'" for e in event_names)
    return f"          AND {event_name_col} IN ({quoted})"


def build_overview_sql(
    schema: TableSchema,
    monitored_params: List[str],
    lookback_days: int = 180,
    mart_fqn: Optional[str] = None,
    filter_event_names: Optional[List[str]] = None,
    source_spec: Optional[dict] = None,
) -> str:
    """
    전체 이벤트 건강도 조회 SQL.

    mart_fqn 지정 시: 일별 집계 mart 에서 base 를 읽어 180일 raw 스캔 제거.
                     null rate(선택 param)만 raw 최근 30일을 추가 스캔.
    미지정 시:       기존처럼 모두 raw 에서 계산.
    """
    # source_spec 기본값 (Amplitude)
    if source_spec is None:
        from src.config import SOURCE_SPECS
        source_spec = SOURCE_SPECS["amplitude"]

    EVENT_NAME_COL = source_spec["event_name_col"]
    EVENT_DATE_EXPR = source_spec["event_date_expr"]
    EVENT_TS_COL = source_spec["event_ts_col"]
    UNIQUE_USER_COL = source_spec["unique_user_col"]
    PARAMS_COL = source_spec["params_col"]
    is_ts = source_spec["event_ts_is_timestamp"]

    def recent(days):
        if is_ts:
            return f"{EVENT_TS_COL} >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())"
        return f"{EVENT_TS_COL} >= DATEADD(day, -{days}, CURRENT_DATE)"

    # 각 param에 대한 null rate 집계식 (nullrates CTE 용, raw 스캔)
    null_rate_exprs = []
    for p in monitored_params:
        safe_col = f'null_rate_{p.lower().replace("-", "_")}'
        expr = (
            f"ROUND(SUM(CASE WHEN {PARAMS_COL}:\"{p}\" IS NULL "
            f"THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0)::FLOAT * 100, 1) "
            f"AS {safe_col}"
        )
        null_rate_exprs.append(expr)

    null_rates_sql = ",\n        ".join(null_rate_exprs) if null_rate_exprs else ""
    null_rates_line = f",\n        {null_rates_sql}" if null_rates_sql else ""

    # user_id null rate: mart 에는 미리 계산된 컬럼이 있으므로 raw 재쿼리 불필요
    user_id_null_expr_raw = ""
    if schema.has_column("USER_ID") and not mart_fqn:
        user_id_null_expr_raw = (
            ",\n        ROUND(SUM(CASE WHEN USER_ID IS NULL THEN 1 ELSE 0 END) "
            "/ NULLIF(COUNT(*),0)::FLOAT * 100, 1) AS null_rate_user_id"
        )

    event_filter = _events_in_clause(filter_event_names, EVENT_NAME_COL)

    # ── base CTE: mart 우선, 없으면 raw ──
    if mart_fqn:
        base_cte = f"""
    base AS (
        SELECT
            event_name,
            event_date,
            event_count,
            unique_users,
            null_rate_user_id_pct
        FROM {mart_fqn}
        WHERE event_date >= DATEADD(day, -{lookback_days}, CURRENT_DATE)
{event_filter}
    )"""
        # mart 에 이미 일별 null_rate_user_id_pct 가 있으므로 30일 가중 평균
        mart_user_id_agg = (
            ",\n        ROUND(SUM(CASE WHEN event_date >= DATEADD(day, -30, CURRENT_DATE) "
            "THEN null_rate_user_id_pct * event_count ELSE 0 END) "
            "/ NULLIF(SUM(CASE WHEN event_date >= DATEADD(day, -30, CURRENT_DATE) "
            "THEN event_count ELSE 0 END), 0), 1) AS null_rate_user_id"
        )
    else:
        base_cte = f"""
    base AS (
        SELECT
            {EVENT_NAME_COL} AS event_name,
            {EVENT_DATE_EXPR} AS event_date,
            COUNT(*) AS event_count,
            COUNT(DISTINCT {UNIQUE_USER_COL}) AS unique_users
        FROM {schema.fqn}
        WHERE {recent(lookback_days)}
{event_filter}
        GROUP BY {EVENT_NAME_COL}, {EVENT_DATE_EXPR}
    )"""
        mart_user_id_agg = ""

    # ── nullrates CTE: 선택 param 이 있을 때만 raw 30일 스캔 ──
    nullrates_cte_and_join = ""
    nullrates_select_line = ""
    if monitored_params or user_id_null_expr_raw:
        nullrates_cte_and_join = f""",
    nullrates AS (
        SELECT
            {EVENT_NAME_COL} AS event_name{user_id_null_expr_raw}{null_rates_line}
        FROM {schema.fqn}
        WHERE {recent(30)}
{event_filter}
        GROUP BY {EVENT_NAME_COL}
    )"""
        nullrates_select_line = "\n        , n.*"
        nullrates_join = "\n    LEFT JOIN nullrates n USING (event_name)"
    else:
        nullrates_join = ""

    sql = f"""
    WITH {base_cte.strip()}{nullrates_cte_and_join},
    aggregated AS (
        SELECT
            event_name,
            MIN(event_date) AS first_seen_date,
            MAX(event_date) AS last_seen_date,
            SUM(event_count) AS total_events_180d,
            SUM(CASE WHEN event_date >= DATEADD(day, -30, CURRENT_DATE)
                     THEN event_count ELSE 0 END) AS events_last_30d,
            SUM(CASE WHEN event_date >= DATEADD(day, -30, CURRENT_DATE)
                     THEN unique_users ELSE 0 END) AS users_last_30d,
            SUM(CASE WHEN event_date BETWEEN DATEADD(day, -60, CURRENT_DATE)
                                         AND DATEADD(day, -31, CURRENT_DATE)
                     THEN event_count ELSE 0 END) AS events_prev_30d{mart_user_id_agg}
        FROM base
        GROUP BY event_name
    )
    SELECT
        a.*,
        DATEDIFF(day, a.last_seen_date, CURRENT_DATE) AS days_since_last_event,
        CASE WHEN a.events_prev_30d = 0 THEN NULL
             ELSE ROUND((a.events_last_30d - a.events_prev_30d)
                        / a.events_prev_30d::FLOAT * 100, 1)
        END AS volume_change_pct{nullrates_select_line}
    FROM aggregated a{nullrates_join}
    ORDER BY a.total_events_180d DESC
    """
    return sql


def build_daily_trend_sql(
    schema: TableSchema,
    event_name: str,
    lookback_days: int = 180,
    source_spec: Optional[dict] = None,
) -> str:
    """특정 이벤트의 일별 트렌드 SQL (Amplitude/GA4 소스 모두 지원)"""
    if source_spec is None:
        from src.config import SOURCE_SPECS
        source_spec = SOURCE_SPECS["amplitude"]

    NAME = source_spec["event_name_col"]
    DATE = source_spec["event_date_expr"]
    TS = source_spec["event_ts_col"]
    USER = source_spec["unique_user_col"]
    is_ts = source_spec["event_ts_is_timestamp"]
    recent = (
        f"{TS} >= DATEADD(day, -{lookback_days}, CURRENT_TIMESTAMP())"
        if is_ts else
        f"{TS} >= DATEADD(day, -{lookback_days}, CURRENT_DATE)"
    )

    safe_name = event_name.replace("'", "''")
    return f"""
        SELECT
            {DATE} AS event_date,
            COUNT(*) AS event_count,
            COUNT(DISTINCT {USER}) AS unique_users,
            COUNT(DISTINCT PLATFORM) AS platform_count
        FROM {schema.fqn}
        WHERE {recent}
          AND {NAME} = '{safe_name}'
        GROUP BY {DATE}
        ORDER BY event_date
    """


def build_param_distribution_sql(
    schema: TableSchema,
    event_name: str,
    param_key: str,
    lookback_days: int = 30,
    top_n: int = 20,
) -> str:
    """특정 이벤트의 특정 param 값 분포 (Amplitude)"""
    safe_name = event_name.replace("'", "''")
    safe_key = param_key.replace('"', '""')
    return f"""
        SELECT
            EVENT_PROPERTIES:"{safe_key}"::STRING AS param_value,
            COUNT(*) AS cnt
        FROM {schema.fqn}
        WHERE EVENT_TIME >= DATEADD(day, -{lookback_days}, CURRENT_DATE)
          AND EVENT_TYPE = '{safe_name}'
        GROUP BY param_value
        ORDER BY cnt DESC
        LIMIT {top_n}
    """


# ──────────────────────────────────────────────────────────────
# 분석 실행 함수
# ──────────────────────────────────────────────────────────────
def run_overview(
    client: SnowflakeClient,
    schema: TableSchema,
    monitored_params: List[str],
    lookback_days: int = 180,
    mart_fqn: Optional[str] = None,
    filter_event_names: Optional[List[str]] = None,
    source_spec: Optional[dict] = None,
) -> pd.DataFrame:
    """선택 이벤트들의 건강도 DataFrame 반환 (분류 컬럼 포함)"""
    sql = build_overview_sql(
        schema, monitored_params, lookback_days, mart_fqn,
        filter_event_names, source_spec,
    )
    try:
        df = client.query(sql)
    except Exception as e:
        raise RuntimeError(
            f"SQL 실행 실패: {e}\n\n=== 생성된 SQL ===\n{sql}"
        ) from e

    if df.empty:
        return df

    # 분류 적용
    classifications = df.apply(
        lambda row: classify_health(
            int(row["days_since_last_event"]),
            float(row["volume_change_pct"]) / 100
                if pd.notna(row["volume_change_pct"]) else None,
            int(row.get("events_last_30d", 0) or 0),
            int(row.get("events_prev_30d", 0) or 0),
        ),
        axis=1,
    )
    df["health_status"] = [c[0] for c in classifications]
    df["recommendation"] = [c[1] for c in classifications]
    return df


def run_daily_trend(
    client: SnowflakeClient,
    schema: TableSchema,
    event_name: str,
    lookback_days: int = 180,
    source_spec: Optional[dict] = None,
) -> pd.DataFrame:
    sql = build_daily_trend_sql(schema, event_name, lookback_days, source_spec)
    return client.query(sql)

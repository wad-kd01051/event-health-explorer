"""
스키마 자동 탐지

1. INFORMATION_SCHEMA.COLUMNS 에서 테이블 컬럼 목록 조회
2. EVENT_PARAMS_FLATTENED 샘플링으로 실제 param 키 발견
3. 발견된 param 중 어떤 것을 null rate 모니터링 대상으로 쓸지 자동 추천
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from src.snowflake_client import SnowflakeClient


@dataclass
class TableSchema:
    database: str
    schema: str
    table: str
    columns: pd.DataFrame          # name, type, ordinal
    flattened_param_keys: List[str]  # EVENT_PARAMS_FLATTENED에서 발견된 키들
    user_properties_keys: List[str]  # USER_PROPERTIES_FLATTENED에서 발견된 키들

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.schema}.{self.table}"

    def has_column(self, name: str) -> bool:
        return name.upper() in self.columns["name"].str.upper().values


def inspect_table(
    client: SnowflakeClient,
    database: str,
    schema: str,
    table: str,
    source_spec: Optional[dict] = None,
    param_sample_size: int = 100_000,
    min_occurrence: float = 0.01,
) -> TableSchema:
    """
    테이블 스키마와 flatten된 param 키를 자동 탐지.
    source_spec 이 있으면 소스별 컬럼명으로 쿼리 (Amplitude/GA4 호환).
    """
    # 1) 컬럼 목록
    cols_df = client.query(f"""
        SELECT COLUMN_NAME AS name, DATA_TYPE AS type, ORDINAL_POSITION AS ordinal
        FROM {database}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema.upper()}'
          AND TABLE_NAME = '{table.upper()}'
        ORDER BY ORDINAL_POSITION
    """)

    if cols_df.empty:
        raise RuntimeError(f"테이블을 찾을 수 없습니다: {database}.{schema}.{table}")

    col_names_upper = cols_df["name"].str.upper().tolist()

    # source_spec 이 없으면 Amplitude 기본값 (레거시)
    if source_spec is None:
        from src.config import SOURCE_SPECS
        source_spec = SOURCE_SPECS["amplitude"]

    params_col = source_spec["params_col"]
    user_props_col = source_spec["user_props_col"]
    ts_col = source_spec["event_ts_col"]
    is_ts = source_spec["event_ts_is_timestamp"]

    recent_where = (
        f"{ts_col} >= DATEADD(day, -1, CURRENT_TIMESTAMP())"
        if is_ts
        else f"{ts_col} >= DATEADD(day, -1, CURRENT_DATE)"
    )

    # 2) EVENT_PROPERTIES (또는 GA4 EVENT_PARAMS_FLATTENED) 키 샘플링
    flattened_keys: List[str] = []
    if params_col in col_names_upper:
        try:
            keys_sql = f"""
                SELECT f.key::STRING AS key, COUNT(*) AS cnt
                FROM (
                    SELECT {params_col}
                    FROM {database}.{schema}.{table}
                    WHERE {recent_where}
                      AND {params_col} IS NOT NULL
                    LIMIT 20000
                ) sub,
                LATERAL FLATTEN(input => {params_col}) f
                GROUP BY f.key
                ORDER BY cnt DESC
                LIMIT 200
            """
            keys_df = client.query(keys_sql)
            flattened_keys = keys_df["key"].tolist() if not keys_df.empty else []
        except Exception:
            pass

    # 3) USER_PROPERTIES 키 샘플링
    user_props_keys: List[str] = []
    if user_props_col in col_names_upper:
        try:
            up_sql = f"""
                SELECT DISTINCT f.key::STRING AS key
                FROM (
                    SELECT {user_props_col}
                    FROM {database}.{schema}.{table}
                    WHERE {recent_where}
                      AND {user_props_col} IS NOT NULL
                    LIMIT 5000
                ) sub,
                LATERAL FLATTEN(input => {user_props_col}) f
                LIMIT 200
            """
            up_df = client.query(up_sql)
            user_props_keys = up_df["key"].tolist() if not up_df.empty else []
        except Exception:
            pass

    return TableSchema(
        database=database,
        schema=schema,
        table=table,
        columns=cols_df,
        flattened_param_keys=flattened_keys,
        user_properties_keys=user_props_keys,
    )


def detect_ga4_event_name_key(
    client: SnowflakeClient,
    database: str,
    schema: str,
    table: str,
    sample_event_values: List[str],
    lookback_days: int = 2,
    row_sample: int = 200_000,
) -> Optional[str]:
    """
    GA4 이벤트명 식별 param key 자동 탐지 (LIMIT 서브쿼리로 고속화).
    최근 N일 중 상위 row_sample 건만 FLATTEN → 매칭.
    """
    if not sample_event_values:
        return None
    quoted = ",".join(
        f"'{v.replace(chr(39), chr(39)*2)}'" for v in sample_event_values[:15]
    )
    sql = f"""
        SELECT
            f.key::STRING AS param_key,
            COUNT(DISTINCT f.value::STRING) AS matched_distinct,
            COUNT(*) AS hits
        FROM (
            SELECT EVENT_PARAMS_FLATTENED
            FROM {database}.{schema}.{table}
            WHERE EVENT_DATE >= DATEADD(day, -{lookback_days}, CURRENT_DATE)
              AND EVENT_PARAMS_FLATTENED IS NOT NULL
            LIMIT {row_sample}
        ) sub,
        LATERAL FLATTEN(input => sub.EVENT_PARAMS_FLATTENED) f
        WHERE f.value::STRING IN ({quoted})
        GROUP BY param_key
        ORDER BY matched_distinct DESC, hits DESC
        LIMIT 1
    """
    try:
        df = client.query(sql)
        if df.empty:
            return None
        return str(df["param_key"].iloc[0])
    except Exception:
        return None

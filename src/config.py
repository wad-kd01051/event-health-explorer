"""
설정 로드 모듈

환경변수 우선순위:
  1. DBT_SNOWFLAKE_* (dbt 프로젝트와 동일한 .env)
  2. SNOWFLAKE_* (앱 전용 override)
  3. ~/.dbt/profiles.yml (나머지 보강)

인증 방식:
  - 비밀번호 없으면 자동으로 externalbrowser (SSO) 사용
  - dbt 프로젝트와 동일한 로그인 흐름
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# .env 자동 로드
load_dotenv()


SOURCE_SPECS = {
    "amplitude": {
        "label": "📊 Amplitude",
        "env_prefix": "AMPLITUDE",
        "default_table": ("WAD_DW_PROD", "STAGING", "STG_AMPLITUDE__AMPLITUDE_EVENTS"),
        "event_name_col": "EVENT_TYPE",
        "event_date_expr": "EVENT_TIME::DATE",
        "event_ts_col": "EVENT_TIME",
        "event_ts_is_timestamp": True,
        "unique_user_col": "AMPLITUDE_ID",
        "user_id_col": "USER_ID",
        "params_col": "EVENT_PROPERTIES",
        "user_props_col": "USER_PROPERTIES",
        "sheet_event_col_candidates": ("event_name",),
    },
    "ga4": {
        "label": "🔵 GA4",
        "env_prefix": "GA4",
        "default_table": ("wad_dw", "dw", "ga4_events_flattend"),
        "event_name_col": "EVENT_NAME",
        "event_date_expr": "EVENT_DATE",
        "event_ts_col": "EVENT_DATE",
        "event_ts_is_timestamp": False,
        "unique_user_col": "USER_PSEUDO_ID",
        "user_id_col": "USER_ID",
        "params_col": "EVENT_PARAMS_FLATTENED",
        "user_props_col": "USER_PROPERTIES_FLATTENED",
        "sheet_event_col_candidates": ("eventName",),
    },
}


def recent_filter(spec: dict, days: int) -> str:
    """소스 스펙에 맞춘 최근 N일 필터 WHERE 조각 (컬럼명 포함)."""
    col = spec["event_ts_col"]
    if spec["event_ts_is_timestamp"]:
        return f"{col} >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())"
    return f"{col} >= DATEADD(day, -{days}, CURRENT_DATE)"


@dataclass
class SourceTable:
    """한 데이터 소스(Amplitude/GA4)의 테이블 위치."""
    database: str
    schema: str
    table: str

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.schema}.{self.table}"


@dataclass
class SnowflakeConfig:
    account: str
    user: str
    warehouse: str
    database: str
    schema: str
    role: Optional[str] = None
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[str] = None
    authenticator: Optional[str] = None  # 'externalbrowser' = SSO

    # 레거시 호환
    events_database: Optional[str] = None
    events_schema: Optional[str] = None
    events_table: str = "GA4_EVENTS"

    # 소스별 테이블 위치
    amplitude: Optional[SourceTable] = None
    ga4: Optional[SourceTable] = None

    # 일별 집계 mart (활성 소스 기준)
    mart_database: Optional[str] = None
    mart_schema: Optional[str] = None
    mart_table: Optional[str] = None

    def resolve_events_fqn(self) -> str:
        db = self.events_database or self.database
        sch = self.events_schema or self.schema
        return f"{db}.{sch}.{self.events_table}"

    def resolve_mart_fqn(self) -> Optional[str]:
        if not self.mart_table:
            return None
        db = self.mart_database or self.events_database or self.database
        sch = self.mart_schema or self.events_schema or self.schema
        return f"{db}.{sch}.{self.mart_table}"

    def get_source_table(self, source: str) -> Optional[SourceTable]:
        return getattr(self, source, None)


@dataclass
class SheetsConfig:
    spreadsheet_url: Optional[str] = None
    worksheet_name: Optional[str] = None
    service_account_json: Optional[str] = None


@dataclass
class AppConfig:
    snowflake: SnowflakeConfig
    sheets: SheetsConfig = field(default_factory=SheetsConfig)


# ──────────────────────────────────────────────────────────────
# dbt profiles.yml 파싱 (env_var 치환 포함)
# ──────────────────────────────────────────────────────────────
def _resolve_env_vars(value):
    """
    dbt의 {{ env_var('FOO') }} 또는 {{ env_var('FOO', 'default') }} 문법을
    실제 환경변수 값으로 치환.
    """
    if isinstance(value, str):
        import re
        pattern = re.compile(
            r"\{\{\s*env_var\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*['\"]([^'\"]*)['\"]\s*)?\)\s*\}\}"
        )

        def replace(match):
            var_name = match.group(1)
            default = match.group(2) or ""
            return os.getenv(var_name, default)

        return pattern.sub(replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def _load_dbt_profile(
    profile_name: Optional[str] = None,
    target: Optional[str] = None,
    profiles_path: Optional[Path] = None,
) -> Optional[dict]:
    """~/.dbt/profiles.yml 에서 지정된 profile/target 설정을 읽어옴."""
    path = profiles_path or Path.home() / ".dbt" / "profiles.yml"
    if not path.exists():
        return None

    with open(path) as f:
        profiles = yaml.safe_load(f)
    profiles = _resolve_env_vars(profiles)

    if profile_name is None:
        for name, conf in profiles.items():
            if name == "config" or not isinstance(conf, dict):
                continue
            outputs = conf.get("outputs", {})
            t = target or conf.get("target")
            if t and t in outputs and outputs[t].get("type") == "snowflake":
                profile_name = name
                break
        if profile_name is None:
            return None

    profile = profiles.get(profile_name)
    if not profile:
        return None

    target = target or profile.get("target")
    output = profile.get("outputs", {}).get(target)
    if not output or output.get("type") != "snowflake":
        return None

    return output


def _detect_sis_env() -> bool:
    """Streamlit in Snowflake 환경인지 감지."""
    try:
        from snowflake.snowpark.context import get_active_session  # type: ignore[import-not-found]
        get_active_session()
        return True
    except Exception:
        return False


def _derive_dev_schema_from_email(email: str, prefix: str = "MART") -> str:
    """
    dbt 프로젝트 규칙:
      seyeon.choi@catchtable.co.kr → MART_SEYEON_CHOI
      kd01051@catchtable.co.kr     → MART_KD01051
    """
    local = email.split("@")[0]
    return f"{prefix}_{local.upper().replace('.', '_')}"


def load_config(
    profile_name: Optional[str] = None,
    target: Optional[str] = None,
) -> AppConfig:
    """
    설정 로드. dbt .env 와 profiles.yml 을 자동 통합.
    우선순위: DBT_SNOWFLAKE_* > SNOWFLAKE_* > profiles.yml
    """
    target = target or os.getenv("DBT_TARGET", "dev")
    profile_name = profile_name or os.getenv("DBT_PROFILE")

    dbt_output = _load_dbt_profile(profile_name, target) or {}

    def pick(dbt_key: str, *env_keys, default=None):
        """환경변수 여러 개 순서대로 시도, 없으면 profiles.yml, 없으면 default"""
        for k in env_keys:
            v = os.getenv(k)
            if v:
                return v
        return dbt_output.get(dbt_key, default)

    # 계정/사용자 — dbt의 .env 이름 우선
    account = pick("account", "DBT_SNOWFLAKE_ACCOUNT", "SNOWFLAKE_ACCOUNT")
    user    = pick("user",    "DBT_SNOWFLAKE_USER",    "SNOWFLAKE_USER")

    # dev 타겟이고 스키마 지정 없으면 이메일 기반으로 자동 도출
    schema = pick("schema", "DBT_SNOWFLAKE_SCHEMA", "SNOWFLAKE_SCHEMA")
    if not schema and user and target == "dev":
        schema = _derive_dev_schema_from_email(user, prefix="MART")

    warehouse = pick(
        "warehouse", "DBT_SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_WAREHOUSE",
        default="ANALYST_WH",
    )
    database = pick(
        "database", "DBT_SNOWFLAKE_DATABASE", "SNOWFLAKE_DATABASE",
    )
    role = pick("role", "DBT_SNOWFLAKE_ROLE", "SNOWFLAKE_ROLE")

    # 인증 방식
    password = pick(
        "password", "DBT_SNOWFLAKE_PASSWORD", "SNOWFLAKE_PASSWORD",
    )
    pk_path = pick(
        "private_key_path",
        "DBT_SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PRIVATE_KEY_PATH",
    )
    pk_pw = pick(
        "private_key_passphrase",
        "DBT_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    )
    authenticator = pick(
        "authenticator",
        "DBT_SNOWFLAKE_AUTHENTICATOR", "SNOWFLAKE_AUTHENTICATOR",
    )

    # 아무 인증 정보도 없으면 SSO로 자동 설정 (dbt 표준 동작)
    if not password and not pk_path and not authenticator:
        authenticator = "externalbrowser"

    # Streamlit in Snowflake(SiS) 환경에서는 active session이 이미 있으므로
    # account/user 체크 생략 (SnowflakeClient가 세션을 자동 감지)
    is_sis = _detect_sis_env()

    if not is_sis and (not account or not user):
        raise RuntimeError(
            "Snowflake 연결 정보가 부족합니다.\n"
            ".env 파일에 다음 항목이 필요합니다:\n"
            "  DBT_SNOWFLAKE_ACCOUNT=BVJAEKO-LA86305\n"
            "  DBT_SNOWFLAKE_USER=본인이메일@catchtable.co.kr\n"
            "  DBT_TARGET=dev\n"
        )

    sf = SnowflakeConfig(
        account=account or "sis",
        user=user or "sis",
        warehouse=warehouse,
        database=database or "ANALYTICS_DB",
        schema=schema or "PUBLIC",
        role=role,
        password=password,
        private_key_path=pk_path,
        private_key_passphrase=pk_pw,
        authenticator=authenticator,
        events_database=os.getenv("EVENTS_DATABASE"),
        events_schema=os.getenv("EVENTS_SCHEMA"),
        events_table=os.getenv("EVENTS_TABLE", "GA4_EVENTS"),
        mart_database=os.getenv("MART_DATABASE"),
        mart_schema=os.getenv("MART_SCHEMA"),
        mart_table=os.getenv("MART_TABLE"),
    )

    # 소스별 테이블 위치 주입 (환경변수 없으면 default)
    for src, spec in SOURCE_SPECS.items():
        prefix = spec["env_prefix"]
        db_def, sch_def, tbl_def = spec["default_table"]
        db = os.getenv(f"{prefix}_DATABASE") or os.getenv("EVENTS_DATABASE") or db_def
        sch = os.getenv(f"{prefix}_SCHEMA") or os.getenv("EVENTS_SCHEMA") or sch_def
        tbl = os.getenv(f"{prefix}_TABLE") or tbl_def
        setattr(sf, src, SourceTable(database=db, schema=sch, table=tbl))

    sheets = SheetsConfig(
        spreadsheet_url=os.getenv("SHEETS_URL"),
        worksheet_name=os.getenv("SHEETS_WORKSHEET"),
        service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
    )

    return AppConfig(snowflake=sf, sheets=sheets)

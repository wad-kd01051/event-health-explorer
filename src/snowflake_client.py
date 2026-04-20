"""
Snowflake 클라이언트

- 로컬 실행: password / key-pair / SSO(externalbrowser) 자동 감지
- Streamlit in Snowflake (SiS): 활성 Snowpark 세션 자동 사용
  → 사용자가 별도 인증 설정 없이 사내 SSO로 바로 접속
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import SnowflakeConfig


def _try_get_active_session():
    """SiS 환경이면 활성 Snowpark 세션 반환, 로컬이면 None."""
    try:
        from snowflake.snowpark.context import get_active_session  # type: ignore[import-not-found]
        return get_active_session()
    except Exception:
        return None


def _load_private_key(path: str, passphrase: Optional[str]) -> bytes:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    pw = passphrase.encode() if passphrase else None
    with open(Path(path).expanduser(), "rb") as f:
        p_key = serialization.load_pem_private_key(
            f.read(), password=pw, backend=default_backend()
        )
    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _connect_local(cfg: SnowflakeConfig):
    """로컬에서 snowflake-connector-python 로 커넥션 생성."""
    import snowflake.connector

    kwargs = {
        "account": cfg.account,
        "user": cfg.user,
        "warehouse": cfg.warehouse,
        "database": cfg.database,
        "schema": cfg.schema,
    }
    if cfg.role:
        kwargs["role"] = cfg.role

    if cfg.authenticator:
        kwargs["authenticator"] = cfg.authenticator
    elif cfg.private_key_path:
        kwargs["private_key"] = _load_private_key(
            cfg.private_key_path, cfg.private_key_passphrase
        )
    elif cfg.password:
        kwargs["password"] = cfg.password
    else:
        raise RuntimeError(
            "인증 정보가 없습니다: password / private_key_path / authenticator "
            "중 하나가 필요합니다."
        )

    # 비용 추적용 QUERY_TAG — Snowflake Usage 에서 이 앱 쿼리만 필터링 가능
    kwargs["session_parameters"] = {"QUERY_TAG": "event_health_explorer"}

    return snowflake.connector.connect(**kwargs)


class SnowflakeClient:
    """로컬 / SiS 양쪽 지원하는 쿼리 실행 래퍼"""

    def __init__(self, cfg: SnowflakeConfig):
        self.cfg = cfg
        self._sis_session = _try_get_active_session()
        self._conn = None

        # SiS 세션엔 QUERY_TAG 를 한 번만 설정
        if self._sis_session is not None:
            try:
                self._sis_session.sql(
                    "ALTER SESSION SET QUERY_TAG = 'event_health_explorer'"
                ).collect()
            except Exception:
                pass

    @property
    def is_sis(self) -> bool:
        return self._sis_session is not None

    @property
    def conn(self):
        if self.is_sis:
            return None
        if self._conn is None or self._conn.is_closed():
            self._conn = _connect_local(self.cfg)
        return self._conn

    def query(self, sql: str, params: Optional[dict] = None) -> pd.DataFrame:
        """SQL 실행 후 DataFrame 반환. 컬럼명 소문자 + 중복 컬럼 제거."""
        if self.is_sis:
            df = self._sis_session.sql(sql).to_pandas()
        else:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params or {})
                df = cur.fetch_pandas_all()
            finally:
                cur.close()

        df.columns = [c.lower() for c in df.columns]
        # JOIN 으로 같은 이름의 컬럼이 2개 이상 들어오면 첫 번째만 유지
        df = df.loc[:, ~df.columns.duplicated()]
        return df

    def close(self):
        if self._conn and not self._conn.is_closed():
            self._conn.close()

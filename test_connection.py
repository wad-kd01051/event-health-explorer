"""
연결 테스트 스크립트

사용법:
    python test_connection.py

앱 실행 전에 Snowflake 연결과 테이블 접근을 먼저 확인할 때 사용.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_config
from src.snowflake_client import SnowflakeClient


def main():
    print("=" * 60)
    print("🔍 설정 로드 중...")
    print("=" * 60)
    try:
        cfg = load_config()
    except Exception as e:
        print(f"❌ 설정 로드 실패: {e}")
        return 1

    print(f"  Account   : {cfg.snowflake.account}")
    print(f"  User      : {cfg.snowflake.user}")
    print(f"  Warehouse : {cfg.snowflake.warehouse}")
    print(f"  Database  : {cfg.snowflake.database}")
    print(f"  Schema    : {cfg.snowflake.schema}")
    print(f"  Role      : {cfg.snowflake.role or '(default)'}")
    auth = "externalbrowser (SSO)" if cfg.snowflake.authenticator == "externalbrowser" \
           else (cfg.snowflake.authenticator or "password")
    print(f"  Auth      : {auth}")
    print(f"  Events table: {cfg.snowflake.resolve_events_fqn()}")

    print()
    print("=" * 60)
    print("🌐 Snowflake 연결 중...")
    if cfg.snowflake.authenticator == "externalbrowser":
        print("   → 브라우저 팝업이 뜨면 SSO 로그인해주세요")
    print("=" * 60)

    client = SnowflakeClient(cfg.snowflake)
    try:
        df = client.query("SELECT CURRENT_USER() AS u, CURRENT_ROLE() AS r, "
                          "CURRENT_WAREHOUSE() AS wh")
        print(f"✅ 연결 성공: {df.iloc[0].to_dict()}")
    except Exception as e:
        print(f"❌ 연결 실패: {e}")
        return 1

    print()
    print("=" * 60)
    print(f"📊 이벤트 테이블 확인: {cfg.snowflake.resolve_events_fqn()}")
    print("=" * 60)
    try:
        fqn = cfg.snowflake.resolve_events_fqn()
        df = client.query(f"""
            SELECT
                COUNT(*) AS total_rows,
                COUNT(DISTINCT EVENT_NAME) AS unique_events,
                MIN(EVENT_DATE) AS earliest,
                MAX(EVENT_DATE) AS latest
            FROM {fqn}
            WHERE EVENT_DATE >= DATEADD(day, -7, CURRENT_DATE)
        """)
        print(f"✅ 최근 7일 데이터 확인:")
        for k, v in df.iloc[0].to_dict().items():
            print(f"     {k}: {v:,}" if isinstance(v, (int, float)) else f"     {k}: {v}")
    except Exception as e:
        print(f"❌ 테이블 접근 실패: {e}")
        print(f"   → .env 의 EVENTS_DATABASE / EVENTS_SCHEMA / EVENTS_TABLE 을 확인해주세요")
        return 1

    print()
    print("✅ 모든 체크 통과. `streamlit run app.py` 로 앱을 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

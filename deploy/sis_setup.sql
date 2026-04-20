-- ============================================================
-- Streamlit in Snowflake (SiS) 배포 준비 SQL
-- ============================================================
-- 아래 항목은 ACCOUNTADMIN(또는 SYSADMIN+보안 권한) 롤이 필요합니다.
-- 본인(ANALYST 등)에게 권한이 없다면 데이터팀/인프라팀에 요청하세요.
--
-- 실행 순서:
--   1. External Access Integration 생성  (Google Sheets 공개 CSV export 접근용)
--   2. 본인 롤에 USAGE 권한 부여
--   3. Streamlit 앱 생성 시 이 integration 을 연결
-- ============================================================

-- 0. 어떤 WH에서 돌릴지 결정 (이미 있으면 생략)
--    앱 전용 XS 웨어하우스 분리 권장
CREATE WAREHOUSE IF NOT EXISTS EVENT_HEALTH_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Event Health Explorer 전용 웨어하우스';

-- 1. Google Sheets 접근을 위한 Network Rule
CREATE OR REPLACE NETWORK RULE GOOGLE_SHEETS_EGRESS
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('docs.google.com', 'sheets.googleapis.com')
  COMMENT = '로그 설계서 Google Sheets CSV export 접근용';

-- 2. External Access Integration
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION GOOGLE_SHEETS_INTEGRATION
  ALLOWED_NETWORK_RULES = (GOOGLE_SHEETS_EGRESS)
  ENABLED = TRUE
  COMMENT = 'Streamlit in Snowflake 에서 Google Sheets 공개 CSV export 호출';

-- 3. 권한 부여 (본인 롤로 교체)
--    예: ANALYST 또는 DATA_ENG 같은 실제 사용하는 롤
GRANT USAGE ON INTEGRATION GOOGLE_SHEETS_INTEGRATION TO ROLE <YOUR_ROLE>;
GRANT USAGE ON WAREHOUSE EVENT_HEALTH_WH TO ROLE <YOUR_ROLE>;
-- 앱이 저장될 DB/스키마에 대한 CREATE STREAMLIT 권한도 필요
GRANT USAGE ON DATABASE <DEPLOY_DB> TO ROLE <YOUR_ROLE>;
GRANT USAGE, CREATE STREAMLIT ON SCHEMA <DEPLOY_DB>.<DEPLOY_SCHEMA> TO ROLE <YOUR_ROLE>;

-- 4. GA4 원본 테이블 SELECT 권한 확인
GRANT USAGE ON DATABASE wad_dw TO ROLE <YOUR_ROLE>;
GRANT USAGE ON SCHEMA wad_dw.dw TO ROLE <YOUR_ROLE>;
GRANT SELECT ON TABLE wad_dw.dw.ga4_events_flattend TO ROLE <YOUR_ROLE>;

-- ============================================================
-- Snowsight UI 에서 Streamlit 앱 생성 시:
--   - Warehouse:           EVENT_HEALTH_WH
--   - External Access:     GOOGLE_SHEETS_INTEGRATION  (선택)
--   - Packages:            requirements-sis.txt 참고
-- ============================================================

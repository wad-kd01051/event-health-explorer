-- ============================================================
-- DIM_EVENT_DAILY_STATS — Dynamic Table 버전
-- ============================================================
-- Snowflake Dynamic Table 을 쓰면 Task/Procedure 없이 자동 refresh.
-- dbt 프로젝트도 이미 dynamic_table materialization 을 표준으로 사용 중.
--
-- 권한 요건:
--   - <MART_DB>.<MART_SCHEMA> 에 CREATE DYNAMIC TABLE
--   - wad_dw.dw.ga4_events_flattend 에 SELECT
--   - <EXEC_WH> USAGE
--
-- 본인 환경에 맞춰 치환:
--   <MART_DB>     → WAD_DW_DEV
--   <MART_SCHEMA> → KD01051
--   <EXEC_WH>     → dbt_dev_wh
-- ============================================================

USE DATABASE <MART_DB>;
CREATE SCHEMA IF NOT EXISTS <MART_SCHEMA>;

-- ============================================================
-- Dynamic Table — 하루 1회 자동 refresh (변경분만)
-- ============================================================
CREATE OR REPLACE DYNAMIC TABLE <MART_DB>.<MART_SCHEMA>.DIM_EVENT_DAILY_STATS
    TARGET_LAG = '1 day'
    WAREHOUSE  = <EXEC_WH>
    REFRESH_MODE = INCREMENTAL
    COMMENT = 'GA4 이벤트 × 일 단위 집계 — Event Health Explorer 앱용'
AS
SELECT
    event_date,
    event_name,
    COUNT(*)                       AS event_count,
    COUNT(DISTINCT user_pseudo_id) AS unique_users,
    COUNT(DISTINCT user_id)        AS unique_logged_in_users,
    ROUND(
        SUM(CASE WHEN user_id IS NULL THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0)::FLOAT * 100,
        2
    )                              AS null_rate_user_id_pct
FROM wad_dw.dw.ga4_events_flattend
WHERE event_date >= DATEADD(day, -400, CURRENT_DATE)
GROUP BY event_date, event_name;

-- ============================================================
-- 확인 쿼리
-- ============================================================
-- 초기 빌드 끝날 때까지 기다린 뒤 (1~2분) 실행:
--
-- SELECT COUNT(*) AS row_cnt,
--        MIN(event_date) AS min_dt,
--        MAX(event_date) AS max_dt,
--        COUNT(DISTINCT event_name) AS event_variety
-- FROM <MART_DB>.<MART_SCHEMA>.DIM_EVENT_DAILY_STATS;
--
-- Refresh 이력 확인:
-- SELECT * FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(
--     NAME => '<MART_DB>.<MART_SCHEMA>.DIM_EVENT_DAILY_STATS'
-- )) ORDER BY REFRESH_START_TIME DESC LIMIT 10;

# 🩺 Event Health Explorer

GA4 / Amplitude 이벤트 사용 현황을 동적으로 분석하는 사내 웹앱.

## ⚡ 2줄로 시작 (팀원용)

```bash
git clone https://github.com/wad-kd01051/event-health-explorer.git
cd event-health-explorer && ./setup.sh
```

- 첫 실행 시 이메일만 한 번 입력 → 자동으로 가상환경/의존성/`.env` 설정
- 브라우저 자동 열림, Snowflake SSO 로그인 팝업 뜨면 로그인
- 두 번째부터는 `./setup.sh` 만 실행하면 바로 앱 시작
- 종료: 터미널에서 `Ctrl+C`

**요구사항**: Python 3.11+ (`brew install python@3.11` — macOS), `git`

권한 필요 시 `@kd01051` 에게 GitHub Collaborator 추가 요청.

---


- **Snowflake 스키마 자동 탐지** — View 미리 만들 필요 없음
- **dbt profiles.yml 재사용** — 별도 인증 설정 불필요
- **로그 설계서(Google Sheets) 대조** — 죽은 이벤트·미정의 이벤트 탐지
- **검색 기반 UX** — 전 조직원이 쓸 수 있는 간단한 인터페이스

## 🚀 다른 팀원이 처음 쓸 때 (Git Clone → 실행)

```bash
# 1) 레포 클론
git clone <repo-url> event-health-explorer
cd event-health-explorer

# 2) 가상환경 + 의존성
python3.11 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# 3) 환경변수 — 본인 이메일만 교체
cp .env.example .env
# .env 열고 DBT_SNOWFLAKE_USER=YOUR_ID@catchtable.co.kr 본인 것으로 변경

# 4) 연결 테스트 (SSO 브라우저 로그인 팝업)
python test_connection.py

# 5) 앱 실행
streamlit run app.py
```

> 🔒 `.env` 는 `.gitignore` 로 git 에서 제외됨. 각자 본인 이메일로 SSO 로그인 → 본인 Snowflake 크레딧 사용 (다른 사람 용량 안 잡아먹음).

---

## 🛠️ 로컬 개발 (VS Code)

### 1. 프로젝트 열기
VS Code에서 이 폴더를 엽니다. `.vscode/settings.json`이 자동으로 `.venv`를 인터프리터로 지정합니다.

### 2. 가상환경 생성 + 의존성 설치

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

VS Code 하단에서 `Python 3.x.x ('.venv')` 인터프리터가 선택됐는지 확인하세요.

### 3. 환경변수 설정

`~/.dbt/profiles.yml`이 이미 있다면 **Snowflake 설정은 건너뛰어도 됩니다.**

```bash
cp .env.example .env
# 에디터에서 .env 열고 필요한 값만 채우기
```

dbt가 여러 프로필을 가지고 있다면 `.env`에:
```
DBT_PROFILE=catchtable_analytics
DBT_TARGET=dev
```

원본 GA4 테이블 위치는 반드시 지정:
```
EVENTS_DATABASE=RAW
EVENTS_SCHEMA=GA4
EVENTS_TABLE=GA4_EVENTS
```

### 4. 실행

**방법 A — VS Code 디버거** (F5 키)
`.vscode/launch.json`에 설정돼 있어 바로 실행됩니다.

**방법 B — 터미널**
```bash
streamlit run app.py
```

http://localhost:8501 에서 접속.

## 📋 Google Sheets 연동

로그 설계서가 구글 스프레드시트라면 두 가지 방법이 있어요.

### 방법 A: 공개 시트 (간단)
시트를 "링크가 있는 모든 사용자" 읽기 권한으로 설정 → URL만 붙여넣으면 CSV export로 자동 로드.

### 방법 B: Service Account (보안 유지)
1. Google Cloud Console → 서비스 계정 생성 → JSON 키 다운로드
2. 스프레드시트를 서비스 계정 이메일에 **보기 권한**으로 공유
3. `.env`에:
```
GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service-account.json
```
또는 JSON 내용을 그대로 환경변수 값으로 넣어도 됨 (Streamlit Cloud 등에서 유용).

## 🚢 배포 옵션

### 옵션 1: Streamlit in Snowflake (★ 추천)
**사내 Snowflake SSO 자동 인증, 별도 서버 불필요.** 코드는 이미 SiS 환경을 자동 감지하도록 돼 있어 수정 없이 동작합니다.

#### ① 사전 준비 (관리자 권한 필요)
[deploy/sis_setup.sql](deploy/sis_setup.sql) 에 있는 SQL 을 **ACCOUNTADMIN** 롤로 실행 (또는 인프라팀에 요청):
- `EVENT_HEALTH_WH` 전용 웨어하우스 생성 (XSMALL)
- `GOOGLE_SHEETS_INTEGRATION` External Access Integration (Google Sheets 공개 CSV export 호출용)
- 본인 롤에 USAGE/SELECT 권한 부여

#### ② 앱 업로드
두 가지 방법 중 택 1.

**방법 A — Snowsight UI에 직접 붙여넣기** (가장 빠름)
1. Snowsight → Projects → Streamlit → **+ Streamlit App**
2. Warehouse: `EVENT_HEALTH_WH`, Location: 원하는 DB/스키마 선택
3. 좌측 파일 트리에서 [app.py](app.py) 내용 복사 붙여넣기
4. 같은 트리에 `src/` 폴더 만들고 [config.py](src/config.py), [snowflake_client.py](src/snowflake_client.py), [schema_inspector.py](src/schema_inspector.py), [event_analyzer.py](src/event_analyzer.py), [sheets_client.py](src/sheets_client.py), `__init__.py` 각각 생성

**방법 B — Snowflake CLI로 업로드** (재배포 자동화)
```bash
snow streamlit deploy --replace
```
루트에 `snowflake.yml`을 만들어 사용. [Snowflake CLI 가이드](https://docs.snowflake.com/en/developer-guide/snowflake-cli-v2/streamlit-apps/overview) 참조.

#### ③ Packages 설정
앱 상단 "Packages" 드롭다운에서 [requirements-sis.txt](requirements-sis.txt) 에 있는 패키지 추가 — `streamlit`, `pandas`, `plotly`, `pyyaml` (snowpark, pyarrow는 기본 탑재).

#### ④ External Access 연결
앱 설정 → **External Access** → `GOOGLE_SHEETS_INTEGRATION` 체크.
(설계서 대조 탭에서 공개 Google Sheets CSV export를 호출하기 위함)

#### ⑤ 공유
앱 URL을 사내 구성원에게 공유. Snowflake 계정이 있는 사람이면 SSO 로그인만 하면 바로 사용 가능.

### 옵션 2: 사내 서버에 Docker로 배포

```bash
# 이미지 빌드
docker build -t event-health-explorer .

# 실행 (환경변수로 인증 주입)
docker run -d \
  --name event-health \
  -p 8501:8501 \
  -e SNOWFLAKE_ACCOUNT=xxxxx \
  -e SNOWFLAKE_USER=xxxxx \
  -e SNOWFLAKE_PASSWORD=xxxxx \
  -e SNOWFLAKE_WAREHOUSE=xxxxx \
  -e SNOWFLAKE_DATABASE=xxxxx \
  -e SNOWFLAKE_SCHEMA=xxxxx \
  -e EVENTS_DATABASE=RAW \
  -e EVENTS_SCHEMA=GA4 \
  -e SHEETS_URL=xxxxx \
  event-health-explorer
```

리버스 프록시(nginx) + 사내 SSO(OAuth2-Proxy) 조합이 일반적:
```
사내 사용자 → nginx (SSO) → streamlit (8501)
```

### 옵션 3: Kubernetes (사내 클러스터가 있다면)
`deployment.yaml` + `Secret`에 인증 정보 주입. Dockerfile 그대로 사용 가능.

### 옵션 4: Streamlit Community Cloud
외부 서비스라서 사내 데이터 접근 시 네트워크 정책 확인 필요. 개인 POC용으로만 추천.

## 📁 프로젝트 구조

```
event_health_explorer/
├── .venv/                        # 가상환경 (gitignore)
├── .vscode/
│   ├── settings.json             # 인터프리터 자동 지정
│   └── launch.json               # F5로 디버그 실행
├── .streamlit/
│   └── config.toml               # 테마/서버 설정
├── .env.example                  # 환경변수 템플릿
├── .gitignore
├── src/
│   ├── config.py                 # dbt profiles 파싱
│   ├── snowflake_client.py       # SF 연결 (password/key/SSO)
│   ├── schema_inspector.py       # 스키마 자동 탐지
│   ├── event_analyzer.py         # 건강도 분석 + SQL 빌더
│   └── sheets_client.py          # Google Sheets 연동
├── app.py                        # Streamlit 메인
├── Dockerfile                    # 배포용
├── requirements.txt
└── README.md
```

## 🔄 운영 팁

- **대규모 테이블일수록 캐시 TTL 중요**: `app.py`의 `@st.cache_data(ttl=3600)` 조정
- **WAREHOUSE 분리 권장**: 앱 전용 XS 웨어하우스를 따로 두면 다른 사용자에게 영향 없음
- **스키마 탐지 주기**: 신규 param이 자주 추가되면 TTL을 짧게 (예: 10분)
- **권한**: 앱 계정에는 `SELECT ON {events_table}` + `USAGE ON WAREHOUSE/SCHEMA`만 있으면 됨

## 🔧 커스터마이징 포인트

| 목적 | 수정 위치 |
|---|---|
| 분류 임계값 변경 (90일 → 60일 등) | `src/event_analyzer.py` `classify_health()` |
| 추가 지표 | `src/event_analyzer.py` `build_overview_sql()` |
| UI 레이아웃 | `app.py` 각 탭 섹션 |
| 테마 색상 | `.streamlit/config.toml` + `app.py`의 `STATUS_COLORS` |

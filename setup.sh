#!/usr/bin/env bash
# ==========================================
# Event Health Explorer — 원샷 셋업 & 실행
# ==========================================
# 최초 실행: 가상환경 생성 + 의존성 설치 + .env 생성 + 앱 실행
# 두 번째부터: 가상환경 활성화 + 앱 실행
# ==========================================
set -e

cd "$(dirname "$0")"

echo "🩺 Event Health Explorer"
echo "========================"

# app.py 가 없으면 잘못된 디렉터리에서 실행 중
if [ ! -f "app.py" ]; then
    echo "❌ 이 스크립트는 event-health-explorer 폴더 안에서 실행해주세요"
    echo "   (git clone 또는 ZIP 압축 해제 후 'cd event-health-explorer')"
    exit 1
fi

# ── Python 3.11 확인 ──
PYTHON_BIN=""
for cand in python3.11 python3.12 python3; do
    if command -v "$cand" &>/dev/null; then
        v=$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        case "$v" in
            3.11|3.12|3.13) PYTHON_BIN="$cand"; break ;;
        esac
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.11+ 필요"
    echo "   macOS: brew install python@3.11"
    echo "   Windows: https://www.python.org/downloads/"
    exit 1
fi
echo "✅ Python: $($PYTHON_BIN --version)"

# ── 가상환경 ──
if [ ! -d ".venv" ]; then
    echo "📦 가상환경 생성..."
    "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ── 의존성 ──
if [ ! -f ".venv/.deps_ok" ]; then
    echo "📥 의존성 설치 (1~2분)..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    touch .venv/.deps_ok
fi
echo "✅ 의존성 OK"

# ── .env 초기 설정 ──
if [ ! -f ".env" ]; then
    echo ""
    echo "⚙️  .env 를 처음 만듭니다"

    # curl | bash 환경 대응: /dev/tty 를 FD 3 에 열어서 사용
    if [ -n "$EVENT_HEALTH_EMAIL" ]; then
        USER_EMAIL="$EVENT_HEALTH_EMAIL"
        echo "📝 환경변수 EVENT_HEALTH_EMAIL 사용: $USER_EMAIL"
    elif exec 3< /dev/tty 2>/dev/null; then
        printf "본인 이메일 (예: hong@catchtable.co.kr): "
        IFS= read -r USER_EMAIL <&3
        exec 3<&-
    else
        echo "❌ 대화형 입력이 불가능한 환경입니다."
        echo "   아래 중 하나로 실행해주세요:"
        echo "   1) 터미널에서 직접:   ./setup.sh"
        echo "   2) 환경변수로 지정:"
        echo "      curl ... | EVENT_HEALTH_EMAIL=you@catchtable.co.kr bash"
        exit 1
    fi

    if [ -z "$USER_EMAIL" ]; then
        echo "❌ 이메일이 입력되지 않았습니다"
        exit 1
    fi

    cp .env.example .env
    # macOS(BSD sed) / Linux(GNU sed) 양쪽 호환
    if sed --version >/dev/null 2>&1; then
        sed -i "s|YOUR_ID@catchtable.co.kr|$USER_EMAIL|g" .env
    else
        sed -i "" "s|YOUR_ID@catchtable.co.kr|$USER_EMAIL|g" .env
    fi
    echo "✅ .env 생성 완료 ($USER_EMAIL)"
fi

# ── Service Account JSON 확보 (설계서 접근용) ──
# kd01051 님이 Google Drive 에 업로드 후 파일 ID 를 여기에 입력.
# 파일 공유 설정: "제한됨" (Catchtable 내부만) 유지할 것.
SA_DRIVE_FILE_ID="1KTyuvO3QCC3uQjquRuYPkGxbmXBwon62"
SA_FILE="service-account.json"

if [ ! -f "$SA_FILE" ] && [ -n "$SA_DRIVE_FILE_ID" ]; then
    echo ""
    echo "🔑 Service Account JSON 이 필요합니다 (설계서 Google Sheets 접근용)"
    echo ""

    DRIVE_URL="https://drive.google.com/uc?export=download&id=$SA_DRIVE_FILE_ID"
    VIEW_URL="https://drive.google.com/file/d/$SA_DRIVE_FILE_ID/view"

    # macOS 에서는 Downloads 폴더 자동 감지
    DOWNLOADS_DIR="${HOME}/Downloads"

    # 1) 기존에 받아놓은 파일 자동 감지
    for existing in "$DOWNLOADS_DIR"/service-account*.json "$DOWNLOADS_DIR"/gen-lang-*.json "$DOWNLOADS_DIR"/*-service-account-*.json; do
        if [ -f "$existing" ]; then
            echo "📦 Downloads 폴더에서 발견: $existing"
            cp "$existing" "$SA_FILE"
            echo "✅ $SA_FILE 복사 완료"
            break
        fi
    done

    # 2) 아직 없으면 브라우저 열어서 다운로드 유도
    if [ ! -f "$SA_FILE" ]; then
        echo "👉 다운로드 링크를 브라우저로 엽니다..."
        sleep 1
        if command -v open &>/dev/null; then
            open "$VIEW_URL"
        elif command -v xdg-open &>/dev/null; then
            xdg-open "$VIEW_URL"
        else
            echo "   수동 오픈: $VIEW_URL"
        fi

        echo ""
        echo "   1) 본인 Google 계정(@catchtable.co.kr) 로 로그인"
        echo "   2) 우측 상단 '다운로드' 아이콘 클릭"
        echo "   3) 다운로드된 JSON 파일이 ~/Downloads/ 에 저장됨"
        echo ""

        # 사용자 입력 대기 (curl|bash 대응)
        if exec 3< /dev/tty 2>/dev/null; then
            printf "다운로드 완료했으면 Enter 를 누르세요: "
            IFS= read -r _ <&3
            exec 3<&-
        fi

        # Downloads 에서 다시 탐색
        for existing in "$DOWNLOADS_DIR"/service-account*.json "$DOWNLOADS_DIR"/gen-lang-*.json "$DOWNLOADS_DIR"/*-service-account-*.json; do
            if [ -f "$existing" ]; then
                mv "$existing" "$SA_FILE"
                echo "✅ $SA_FILE 로 이동 완료"
                break
            fi
        done
    fi

    if [ ! -f "$SA_FILE" ]; then
        echo "❌ $SA_FILE 을 찾을 수 없습니다."
        echo "   수동으로 $(pwd)/$SA_FILE 에 저장한 뒤 다시 실행:  ./setup.sh"
        exit 1
    fi

    # .env 에 SA 경로 활성화
    if grep -q "^# GOOGLE_SERVICE_ACCOUNT_JSON=" .env; then
        if sed --version >/dev/null 2>&1; then
            sed -i "s|^# GOOGLE_SERVICE_ACCOUNT_JSON=.*|GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json|" .env
        else
            sed -i "" "s|^# GOOGLE_SERVICE_ACCOUNT_JSON=.*|GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json|" .env
        fi
        echo "✅ .env 의 GOOGLE_SERVICE_ACCOUNT_JSON 활성화"
    elif ! grep -q "^GOOGLE_SERVICE_ACCOUNT_JSON=" .env; then
        echo "GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json" >> .env
    fi
fi

# ── 실행 ──
echo ""
echo "🚀 앱 실행 — 브라우저가 자동으로 열립니다"
echo "   (첫 쿼리 시 Snowflake SSO 로그인 팝업이 뜨면 로그인)"
echo "   종료: Ctrl+C"
echo ""
streamlit run app.py

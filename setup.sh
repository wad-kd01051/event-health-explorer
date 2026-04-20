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

# ── 실행 ──
echo ""
echo "🚀 앱 실행 — 브라우저가 자동으로 열립니다"
echo "   (첫 쿼리 시 Snowflake SSO 로그인 팝업이 뜨면 로그인)"
echo "   종료: Ctrl+C"
echo ""
streamlit run app.py

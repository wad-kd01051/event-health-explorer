#!/usr/bin/env bash
# ==========================================
# Event Health Explorer — 배포용 번들 빌드
# ==========================================
# venv 포함한 전체 패키지를 tar.gz 로 만들어 공유 가능.
# 팀원은 Python 설치 없이 압축 풀고 ./setup.sh 만 실행.
#
# ⚠️ 주의
#   - 빌드한 머신과 동일한 macOS 아키텍처(Apple Silicon vs Intel)에서만 동작
#   - service-account.json / .env 는 절대 포함 안 됨 (별도 전달)
# ==========================================
set -e

cd "$(dirname "$0")"

BUNDLE_NAME="event-health-explorer-$(date +%Y%m%d)"
OUTPUT="${BUNDLE_NAME}.tar.gz"

echo "🩺 Event Health Explorer — 번들 빌드"
echo "==================================="

# ── Python 버전 + 아키텍처 확인 ──
ARCH=$(uname -m)
OS=$(uname -s)
echo "💻 빌드 환경: $OS / $ARCH"
echo ""

# ── 클린 venv 생성 ──
if [ -d ".venv-bundle" ]; then
    echo "🧹 이전 번들용 venv 삭제"
    rm -rf .venv-bundle
fi

echo "📦 클린 가상환경 생성..."
python3.11 -m venv .venv-bundle

# shellcheck disable=SC1091
source .venv-bundle/bin/activate
pip install -q --upgrade pip

echo "📥 의존성 설치..."
pip install -q -r requirements.txt

# 의존성 설치 완료 마킹 (setup.sh 에서 pip install 재실행 방지)
touch .venv-bundle/.deps_ok
deactivate

# ── 번들링 (임시 디렉터리에 복사 후 tar) ──
echo "📁 파일 복사..."
TMPDIR_BUILD=$(mktemp -d)
TARGET_DIR="$TMPDIR_BUILD/$BUNDLE_NAME"
mkdir -p "$TARGET_DIR"

# 현재 프로젝트 → 임시 타깃 (제외할 것들 제외)
rsync -a \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='service-account.json' \
    --exclude='client_secret.json' \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='*.log' \
    --exclude='logs' \
    --exclude='tmp' \
    --exclude='*.tar.gz' \
    --exclude='make-bundle.sh' \
    --exclude='.venv' \
    ./ "$TARGET_DIR/"

# .venv-bundle → .venv 이름으로 번들 안에서 사용
mv "$TARGET_DIR/.venv-bundle" "$TARGET_DIR/.venv"

echo "📦 tar.gz 압축..."
tar -czf "$OUTPUT" -C "$TMPDIR_BUILD" "$BUNDLE_NAME"

# 정리
rm -rf "$TMPDIR_BUILD"
rm -rf .venv-bundle

# ── 결과 ──
SIZE=$(du -h "$OUTPUT" | cut -f1)
echo ""
echo "✅ 빌드 완료"
echo "   파일: $(pwd)/$OUTPUT"
echo "   크기: $SIZE"
echo "   아키텍처: $ARCH (받는 사람도 동일해야 함)"
echo ""
echo "📤 공유: 이 파일을 Slack DM / 사내 공유 드라이브에 업로드"
echo "   받는 사람 가이드는 BUNDLE_README.md 참고"

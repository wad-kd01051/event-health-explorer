#!/usr/bin/env bash
# ==========================================
# Event Health Explorer — 원라인 부트스트래퍼
# ==========================================
# 사용:
#   curl -sSL https://raw.githubusercontent.com/wad-kd01051/event-health-explorer/main/bootstrap.sh | bash
#
# 동작:
#   - 현재 디렉터리에 event-health-explorer 폴더 생성 (없으면)
#   - 이미 있으면 git pull 로 최신화
#   - setup.sh 자동 실행 (가상환경 + 의존성 + .env + 앱)
# ==========================================
set -e

REPO_URL="https://github.com/wad-kd01051/event-health-explorer.git"
DIR="event-health-explorer"

echo "🩺 Event Health Explorer — Bootstrap"
echo "===================================="

# ── git 확인 ──
if ! command -v git &>/dev/null; then
    echo "❌ git 이 필요합니다"
    echo "   macOS: xcode-select --install  또는  brew install git"
    exit 1
fi

# ── clone 또는 업데이트 ──
if [ -d "$DIR/.git" ]; then
    echo "📂 기존 폴더 발견 — 최신화"
    (cd "$DIR" && git pull --rebase)
else
    echo "📥 레포 다운로드"
    git clone "$REPO_URL" "$DIR"
fi

# ── setup.sh 실행 ──
cd "$DIR"
chmod +x setup.sh
exec ./setup.sh

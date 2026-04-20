# 🩺 Event Health Explorer — 번들 설치 가이드

**Python 설치 없이** 앱을 실행하는 방법입니다.

## 🖥️ 사전 체크

이 번들은 **macOS Apple Silicon (M1/M2/M3)** 전용입니다.
터미널에서 확인:
```bash
uname -m
```
- `arm64` 가 나오면 ✅
- `x86_64` 면 ❌ — GitHub 에서 clone 방식 사용 권장 (README 참고)

## 📥 설치 (3 단계)

### 1. 압축 풀기
Slack/메일로 받은 `event-health-explorer-YYYYMMDD.tar.gz` 를 **원하는 곳**(예: `~/`)에 두고:

```bash
cd ~
tar -xzf event-health-explorer-*.tar.gz
cd event-health-explorer-*
```

### 2. Service Account JSON 배치
관리자(@kd01051)에게 Slack DM 으로 `service-account.json` 받아서 이 폴더에 저장:
```bash
# Downloads 에서 가져오기
mv ~/Downloads/service-account.json ./
```

### 3. 실행
```bash
./setup.sh
```

- 이메일 입력
- Snowflake SSO 로그인 (브라우저 팝업)
- 자동으로 http://localhost:8501 열림

---

## ⏭️ 이후 실행

처음 이후부턴 **한 줄**만:
```bash
cd ~/event-health-explorer-YYYYMMDD
./setup.sh
```

종료는 `Ctrl+C`.

---

## 🆘 문제 해결

| 증상 | 해결 |
|---|---|
| `Permission denied: ./setup.sh` | `chmod +x setup.sh` |
| `dyld: Library not loaded` 류 | 아키텍처 불일치 — `uname -m` 결과 공유 |
| `service-account.json 을 찾을 수 없습니다` | JSON 파일을 폴더 루트에 놓았는지 확인 |
| Snowflake 접근 에러 | 본인 Snowflake 계정/롤 확인, 데이터팀 문의 |

막히면 @kd01051 문의.

---

## 🔄 업데이트

새 번들 받으면 기존 폴더 삭제 후 동일 절차. `.env` 와 `service-account.json` 은 백업했다가 새 폴더에 복사:
```bash
cp 기존폴더/.env 새폴더/
cp 기존폴더/service-account.json 새폴더/
```

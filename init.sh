#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: '$1' 명령을 찾을 수 없습니다." >&2
    exit 1
  fi
}

require_command uv

# ── Node.js ────────────────────────────────────────────────────────────────
# frontend(Vite 8)는 Node 22.13+ 를 요구한다. 셸 기본 버전이 낮더라도 버전 매니저가 있으면
# `.nvmrc` 에 적힌 버전을 이 스크립트 안에서만 활성화한다 — 사용자 셸 설정은 건드리지 않는다.
NODE_MIN_MAJOR=22
NODE_MIN_MINOR=13

node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  local version major minor
  version="$(node --version 2>/dev/null)" || return 1
  major="${version#v}"; major="${major%%.*}"
  minor="${version#v*.}"; minor="${minor%%.*}"
  case "$major$minor" in *[!0-9]*) return 1 ;; esac
  [ "$major" -gt "$NODE_MIN_MAJOR" ] && return 0
  [ "$major" -eq "$NODE_MIN_MAJOR" ] && [ "$minor" -ge "$NODE_MIN_MINOR" ]
}

activate_node_with_fnm() {
  command -v fnm >/dev/null 2>&1 || return 1
  eval "$(fnm env)" >/dev/null 2>&1 || return 1
  fnm use --install-if-missing >/dev/null 2>&1
}

activate_node_with_nvm() {
  local nvm_sh="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  [ -s "$nvm_sh" ] || return 1
  # nvm.sh 는 `set -u` 환경에서 unbound variable 로 죽는다.
  set +u
  # shellcheck disable=SC1090
  . "$nvm_sh" >/dev/null 2>&1 || { set -u; return 1; }
  if ! nvm use >/dev/null 2>&1; then
    echo "==> Installing Node $(cat .nvmrc) via nvm"
    nvm install >/dev/null 2>&1 || true
    nvm use >/dev/null 2>&1 || true
  fi
  set -u
  node_version_ok
}

if ! node_version_ok; then
  current="$(command -v node >/dev/null 2>&1 && node --version || echo '없음')"
  activate_node_with_fnm >/dev/null 2>&1 || activate_node_with_nvm >/dev/null 2>&1 || true
  if node_version_ok; then
    echo "==> Node $(node --version) activated from .nvmrc (셸 기본: $current)"
  else
    echo "ERROR: Node.js ${NODE_MIN_MAJOR}.${NODE_MIN_MINOR}+ 가 필요합니다 (현재: $current)." >&2
    echo "       nvm 사용 시: nvm install && nvm use" >&2
    echo "       또는 https://nodejs.org 에서 $(cat .nvmrc) 이상을 설치하세요." >&2
    exit 1
  fi
fi

require_command node
require_command npm

echo "==> Working directory: $PWD"

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "==> Created backend/.env from .env.example (로컬 모델 기본, API 키 불필요)"
fi

# ── Local LLM (optional) ────────────────────────────────────────────────────
# 에이전트 실행은 기본적으로 로컬 Ollama(qwen3:8b)를 사용한다. 없어도 DB/API/테스트는 전부
# 동작하고 통합 테스트는 대역을 쓰므로, 여기서는 준비 여부만 판별하고 진행한다.
LLM_MODEL_NAME="${LLM_MODEL:-qwen3:8b}"
LLM_READY=0

if ! command -v ollama >/dev/null 2>&1; then
  echo "==> [0/5] Local LLM: ollama 미설치 — 에이전트 실행 검증은 건너뜁니다."
  echo "           https://ollama.com/download 설치 후 'ollama pull $LLM_MODEL_NAME'"
  echo "           호스팅 백엔드를 쓰려면 backend/.env 의 LLM_BASE_URL/LLM_MODEL 을 바꾸세요."
elif ! ollama list >/dev/null 2>&1; then
  echo "==> [0/5] Local LLM: ollama 서버가 응답하지 않습니다 — 'ollama serve' 를 실행하세요."
elif ollama list | awk 'NR>1 {print $1}' | grep -qx "$LLM_MODEL_NAME"; then
  echo "==> [0/5] Local LLM ready: $LLM_MODEL_NAME"
  LLM_READY=1
elif [ "${PULL_MODEL:-0}" = "1" ]; then
  echo "==> [0/5] Pulling local model: $LLM_MODEL_NAME"
  ollama pull "$LLM_MODEL_NAME"
  LLM_READY=1
else
  echo "==> [0/5] Local LLM: '$LLM_MODEL_NAME' 모델이 없습니다."
  echo "           'ollama pull $LLM_MODEL_NAME' 또는 'PULL_MODEL=1 ./init.sh' 로 받으세요."
fi

if [ "${SKIP_DB:-0}" != "1" ]; then
  require_command docker
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon이 실행 중이 아닙니다." >&2
    echo "       Docker Desktop을 시작하거나, 코드 검증만 하려면 SKIP_DB=1 ./init.sh 를 사용하세요." >&2
    exit 1
  fi

  echo "==> [1/5] Starting PostgreSQL"
  docker compose up -d --wait
else
  echo "==> [1/5] Skipping PostgreSQL (SKIP_DB=1)"
fi

echo "==> [2/5] Installing locked dependencies"
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  (cd backend && uv sync --locked)
  (cd frontend && npm ci)
else
  echo "    Dependency installation skipped (SKIP_INSTALL=1)"
fi

if [ "${SKIP_DB:-0}" != "1" ]; then
  echo "==> [3/5] Applying database migrations"
  (cd backend && uv run alembic upgrade head)

  if [ "${SEED_DB:-0}" = "1" ]; then
    echo "==> Seeding demo data"
    (cd backend && uv run python -m app.seed)
    (cd backend && uv run python ../seed_notices.py)
    (cd backend && uv run python ../seed_trust.py)
  fi
else
  echo "==> [3/5] Skipping database migrations (SKIP_DB=1)"
fi

if [ "${SKIP_VERIFY:-0}" != "1" ]; then
  # 단위·계약 테스트와 PostgreSQL 통합 테스트가 한 번에 돈다.
  # DB 가 없으면(SKIP_DB=1) 통합 테스트는 스스로 skip 하므로 이 명령은 그대로 통과한다.
  echo "==> [4/5] Backend tests"
  (cd backend && uv run python -m unittest discover -s tests -v)

  echo "==> [5/5] Frontend quality gates"
  (cd frontend && npm run lint)
  (cd frontend && npm run build)

  # npm audit 은 외부 레지스트리에 의존한다. 레지스트리 장애(503)로 셋업 전체가 실패하면
  # 안 되므로 결과만 알리고 진행한다. 강제 게이트가 필요하면 CI 에서 별도로 돌린다.
  if ! (cd frontend && npm audit --audit-level=high); then
    echo "    WARNING: npm audit 이 통과하지 못했습니다 (취약점 또는 레지스트리 오류)." >&2
    echo "             'cd frontend && npm audit' 로 직접 확인하세요." >&2
  fi

  # 스택이 실제로 붙어서 동작하는지까지 확인한다. DB 변경은 스크립트가 롤백한다.
  if [ "${SKIP_DB:-0}" != "1" ]; then
    echo "==> Verifying the running stack end to end"
    if [ "$LLM_READY" = "1" ]; then
      uv run --project backend python backend/scripts/verify_local_stack.py
    else
      echo "    (로컬 LLM 미준비 — 에이전트 실행 검증은 건너뛰고 DB/브로커 경로만 확인합니다)"
      uv run --project backend python backend/scripts/verify_local_stack.py --skip-llm
    fi
  fi
else
  echo "==> [4/5] Verification skipped (SKIP_VERIFY=1)"
fi

if [ "${RUN_APP:-0}" = "1" ]; then
  if [ "${SKIP_DB:-0}" = "1" ]; then
    echo "ERROR: RUN_APP=1 requires PostgreSQL. Remove SKIP_DB=1." >&2
    exit 1
  fi
  echo "==> Starting Backend and Frontend"
  (cd backend && uv run uvicorn app.main:app --reload --port 8000) &
  backend_pid=$!
  trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM
  cd frontend
  npm run dev
fi

echo "==> MeshBoard initialization completed"

# RUN_APP 없이 끝난 경우, 실제로 플랫폼을 열어보는 방법을 알려준다.
# init.sh 는 "환경 준비 + 검증"까지만 하고 서버는 띄우지 않는다.
if [ "${RUN_APP:-0}" != "1" ]; then
  cat <<'HINT'

    플랫폼을 실제로 띄우려면:

      SEED_DB=1 RUN_APP=1 ./init.sh      # 데모 데이터 + backend/frontend 실행

    또는 터미널 두 개로 나눠서:

      cd backend  && uv run uvicorn app.main:app --reload --port 8000
      cd frontend && npm run dev

      Frontend  http://localhost:5173     데모 계정  admin@meshboard.io / admin1234
      Swagger   http://localhost:8000/docs
HINT
fi

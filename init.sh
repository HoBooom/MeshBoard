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
require_command npm
require_command node

node_major="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
node_minor="$(node --version | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
if [ "$node_major" -lt 22 ] || { [ "$node_major" -eq 22 ] && [ "$node_minor" -lt 13 ]; }; then
  echo "ERROR: Node.js 22.13+가 필요합니다 (현재: $(node --version))." >&2
  exit 1
fi

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
  (cd frontend && npm audit --audit-level=high)

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

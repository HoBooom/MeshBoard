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

if [ "${SKIP_DB:-0}" != "1" ]; then
  require_command docker
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon이 실행 중이 아닙니다." >&2
    echo "       Docker Desktop을 시작하거나, 코드 검증만 하려면 SKIP_DB=1 ./init.sh 를 사용하세요." >&2
    exit 1
  fi

  echo "==> [1/4] Starting PostgreSQL"
  docker compose up -d --wait
else
  echo "==> [1/4] Skipping PostgreSQL (SKIP_DB=1)"
fi

echo "==> [2/4] Installing locked dependencies"
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  (cd backend && uv sync --locked)
  (cd frontend && npm ci)
else
  echo "    Dependency installation skipped (SKIP_INSTALL=1)"
fi

if [ "${SKIP_DB:-0}" != "1" ]; then
  echo "==> [3/4] Applying database migrations"
  (cd backend && uv run alembic upgrade head)

  if [ "${SEED_DB:-0}" = "1" ]; then
    echo "==> Seeding demo data"
    (cd backend && uv run python -m app.seed)
    (cd backend && uv run python ../seed_notices.py)
    (cd backend && uv run python ../seed_trust.py)
  fi
else
  echo "==> [3/4] Skipping database migrations (SKIP_DB=1)"
fi

if [ "${SKIP_VERIFY:-0}" != "1" ]; then
  echo "==> [4/4] Running backend tests and frontend quality gates"
  (cd backend && uv run python -m unittest discover -s tests -v)
  (cd frontend && npm run lint)
  (cd frontend && npm run build)
else
  echo "==> [4/4] Verification skipped (SKIP_VERIFY=1)"
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

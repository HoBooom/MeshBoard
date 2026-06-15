#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "==> Working directory: $PWD"

# --- [설정 구간] ---
DB_CMD=(docker compose up -d)
BE_SYNC=(uv sync)
BE_MIGRATE=(uv run alembic upgrade head)
BE_SEED=(uv run python -m app.seed)
BE_START=(uv run uvicorn app.main:app --reload --port 8000)

FE_INSTALL=(npm install)
FE_VERIFY=(npm test)
FE_START=(npm run dev)

# --- [실행 구간] ---

echo "==> [1/3] Starting Infrastructure (Docker & uv sync)"
"${DB_CMD[@]}"

cd backend && "${BE_SYNC[@]}" && cd ..

cd frontend
if [ ! -d "node_modules" ]; then
  echo "==> Installing frontend dependencies..."
  "${FE_INSTALL[@]}"
fi
cd ..

echo "==> [2/3] Running Database Migrations"
cd backend
"${BE_MIGRATE[@]}"

if [ "${SEED_DB:-0}" = "1" ]; then
  echo "==> Seeding database..."
  "${BE_SEED[@]}"
  echo "==> Seeding notices (도시관리 + 사내 공지)..."
  uv run python ../seed_notices.py
  echo "==> Seeding trust data (정책/인증)..."
  uv run python ../seed_trust.py
fi
cd ..

# 3. 애플리케이션 시작 (Startup command)
if [ "${RUN_APP:-0}" = "1" ]; then
  echo "==> [3/3] Starting the Application Sessions"
  
  cd backend && "${BE_START[@]}" & 
  cd frontend && exec "${FE_START[@]}"
else
  echo "Set RUN_APP=1 to launch Backend and Frontend automatically."
fi
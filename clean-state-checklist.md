# Clean State Checklist

## Session 002 체크 (2026-04-24)

- [x] The standard startup path still works.
  - `docker compose up -d` → meshboard-postgres healthy
  - `cd backend && uv run alembic upgrade head` → 18개 테이블 전체 및 익스텐션 마이그레이션 완료
  - `uv run uvicorn app.main:app --reload --port 8000` → 정상 기동
- [x] The standard verification path still runs.
  - `curl http://localhost:8000/health` → `{"status":"healthy"}`
  - `docker exec meshboard-postgres psql -U meshboard -d meshboard -c "\dx"` → 익스텐션 정상
- [x] Current progress is recorded in the progress log.
  - `progress.md` → Session 002 업데이트 완료
- [x] Feature state reflects what is actually passing versus unverified.
  - `feature_list.json` → PH1-db-001: `"status": "passing"`, evidence 기록 완료
- [x] No half-finished step is left undocumented.
- [ ] The next session can continue without manual repair.

## Session 001 체크 (2026-04-24)

- [x] The standard startup path still works.
  - `docker compose up -d` → meshboard-postgres healthy
  - `cd backend && uv run alembic upgrade head` → 마이그레이션 완료
  - `uv run uvicorn app.main:app --reload --port 8000` → 정상 기동
- [x] The standard verification path still runs.
  - `curl http://localhost:8000/health` → `{"status":"healthy"}`
  - `POST /api/v1/auth/login` → JWT 발급 확인
  - `GET /api/v1/auth/admin-only` (evaluator) → 403 확인
- [x] Current progress is recorded in the progress log.
  - `progress.md` → Session 001 업데이트 완료
- [x] Feature state reflects what is actually passing versus unverified.
  - `feature_list.json` → PH1-auth-001: `"status": "passing"`, evidence 기록 완료
- [x] No half-finished step is left undocumented.
  - 미완: Frontend `npm run dev` 확인, bcrypt 경고 → progress.md의 Known risk에 기록
- [ ] The next session can continue without manual repair.
  - **주의**: `docker compose down -v` 후 재시작 시 `uv run alembic upgrade head && uv run python -m app.seed` 재실행 필요
  - **주의**: bcrypt 4.x 고정 (`<5.0`) — `uv sync` 시 자동 적용됨

## 다음 세션 시작 체크리스트

```bash
# 1. DB 기동 확인
docker compose up -d
docker exec meshboard-postgres psql -U meshboard -d meshboard -c "\dt"

# 2. 백엔드 기동
cd backend && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. 프론트엔드 기동
cd frontend && npm run dev

# 4. 헬스체크
curl http://localhost:8000/health
```
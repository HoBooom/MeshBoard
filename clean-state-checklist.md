# Clean State Checklist

## Portfolio v1.0 체크 (2026-09-03)

- [x] PostgreSQL이 healthy이고 Alembic head가 `015_member_role`이다.
- [x] 기존 workspace member 역할이 데이터 손실 없이 `developer`로 정규화됐다.
- [x] Backend unittest 58개가 통과한다.
- [x] Frontend ESLint와 TypeScript/Vite production build가 통과한다.
- [x] Sandbox E2E에서 운영 Interaction 수가 변하지 않고 production write가 0이다.
- [x] 정책 위반 차단, 런타임 Suspend/Activate, explicit target receipt, execution tree 조회가 실제 API에서 검증됐다.
- [x] Archive UPDATE/DELETE 방지 trigger가 enabled 상태다.
- [x] `feature_list.json`의 18개 기능이 모두 passing이며 근거가 기록됐다.
- [x] README, architecture, portfolio guide와 progress log가 현재 구현을 설명한다.
- [x] `.nvmrc`/`.node-version`과 CI가 Node 22.13 기준을 고정한다.
- [x] `node_modules`, `dist`, bytecode, `.env`는 Git 추적 대상이 아니다.
- [x] 로컬 RunYour credit 부족은 코드 결함과 구분해 `progress.md`에 기록했다.

## Session 003 체크 (2026-04-24)

- [x] The standard startup path still works.
  - `docker compose up -d` → meshboard-postgres healthy
  - `cd backend && uv run uvicorn app.main:app --reload --port 8000` → 정상 기동
  - `cd frontend && npm run dev` → 정상 기동
- [x] The standard verification path still runs.
  - `curl http://localhost:8000/health` → `{"status":"healthy"}`
- [x] Current progress is recorded in the progress log.
  - `progress.md` → Session 003 업데이트 완료
- [x] Feature state reflects what is actually passing versus unverified.
  - `feature_list.json` → PH1-dash-001: `"status": "passing"`, evidence 기록 완료
- [x] No half-finished step is left undocumented.
- [ ] The next session can continue without manual repair.

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

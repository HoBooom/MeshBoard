# Progress Log

## Current Verified State

- **Repository root**: `/Users/hobongs/Desktop/HoBong_study/26-1/meshboard`
- **Standard startup path**: `./init.sh` (또는 수동: docker compose up -d → alembic upgrade head → uvicorn)
- **Standard verification path**: `curl http://localhost:8000/health`
- **Current highest-priority unfinished feature**: `PH2-market-001` (priority 4 — 자연어 기반 에이전트 마켓플레이스 검색)
- **Current blocker**: 없음

---

## Session Log

### Session 001
- **Date**: 2026-04-23 ~ 2026-04-24
- **Goal**: PH1-auth-001 — 기업 IdP 연동 및 RBAC 기반 로그인 구현
- **Completed**:
  - Backend 프로젝트 초기 세팅 (FastAPI + uv + pyproject.toml)
  - SQLAlchemy 2.0 async 모델 (User, UserRole)
  - Alembic 비동기 마이그레이션 설정 및 `001_create_users_and_roles` 실행 완료
  - JWT 인증 (python-jose HS256) + bcrypt 비밀번호 해싱 (bcrypt 4.x 고정)
  - RBAC 의존성 (`RequireRoles` 클래스)
  - OIDC 추상화 레이어 (`MockOIDCProvider`)
  - Auth API 엔드포인트 4개: `/login`, `/register`, `/me`, `/refresh`, `/admin-only`
  - 시드 데이터 4명 (admin/dev/ops/user 역할별)
  - Frontend 프로젝트 초기 세팅 (Vite + React 18 + TypeScript + Tailwind CSS 3)
  - Axios JWT 인터셉터, Zustand Auth Store
  - 프리미엄 LoginPage (Split layout, glassmorphism, demo account quick-fill)
  - DashboardLayout (사이드바 + RBAC 기반 네비 필터링)
  - DashboardPage (역할 배지, 시스템 상태, 사용자 정보)
  - ProtectedRoute (미인증 리다이렉트 + 403 페이지)
- **Verification run**:
  - ✅ `docker exec meshboard-postgres psql -U meshboard -d meshboard -c "\dt"` → users, user_roles 테이블 확인
  - ✅ `uv run alembic upgrade head` → 마이그레이션 성공
  - ✅ `uv run python -m app.seed` → 4명 시드 데이터 생성 완료
  - ✅ `curl http://localhost:8000/health` → `{"status":"healthy"}`
  - ✅ `POST /api/v1/auth/login (admin)` → JWT 발급, payload에 `roles: ["governance","trust_ops"]` 포함 확인
  - ✅ `GET /api/v1/auth/admin-only` with evaluator token → 403 응답 (`이 작업에는 다음 역할 중 하나가 필요합니다: governance, trust_ops`)
  - ✅ `GET /api/v1/auth/admin-only` with admin token → 200 응답
  - ✅ `npm install` in frontend → 160 패키지 설치 완료
- **Evidence captured**:
  - JWT 페이로드: `{"sub":"dec943df-…","email":"admin@meshboard.io","roles":["governance","trust_ops"],"type":"access"}`
  - 403 응답: `{"detail":"이 작업에는 다음 역할 중 하나가 필요합니다: governance, trust_ops"}`
- **Commits**: 미커밋 (다음 작업 후 커밋 예정)
- **Files or artifacts updated**:
  - `backend/pyproject.toml`, `backend/.env`, `backend/alembic.ini`
  - `backend/alembic/env.py`, `backend/alembic/versions/001_create_users_and_roles.py`
  - `backend/app/main.py`, `backend/app/seed.py`
  - `backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/core/rbac.py`, `backend/app/core/oidc.py`
  - `backend/app/db/base.py`, `backend/app/db/session.py`
  - `backend/app/models/user.py`
  - `backend/app/schemas/auth.py`
  - `backend/app/api/v1/auth.py`
  - `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`
  - `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/index.html`
  - `frontend/src/index.css`, `frontend/src/main.tsx`, `frontend/src/App.tsx`
  - `frontend/src/api/client.ts`, `frontend/src/api/auth.ts`
  - `frontend/src/stores/authStore.ts`
  - `frontend/src/components/ProtectedRoute.tsx`
  - `frontend/src/layouts/DashboardLayout.tsx`
  - `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/DashboardPage.tsx`
- **Known risk or unresolved issue**:
  - passlib + bcrypt 4.x 경고 메시지 (`error reading bcrypt version`) — 동작에는 영향 없으나 추후 `bcrypt` 직접 사용 또는 `passlib` 업데이트 고려
  - Frontend 빌드 (`npm run dev`) 미검증 — Session 002에서 확인
- **Next best step**: `PH1-dash-001` — 홈 대시보드 및 타겟팅 공지 시스템 (NOTICES) 구현

### Session 002
- **Date**: 2026-04-24
- **Goal**: PH1-db-001 — 레지스트리 18개 테이블 스키마 및 확장 모듈 마이그레이션
- **Completed**:
  - `pyproject.toml`에 `sqlalchemy-utils`, `pgvector` 추가
  - `schema_v1.sql` 기준 15개 핵심 테이블에 대한 SQLAlchemy ORM 모델 구축 (agent, workspace, policy, conversation 등)
  - 모든 DateTime 필드를 `TIMESTAMPTZ`로 통일
  - Alembic을 활용한 통합 마이그레이션(`002_create_registry_tables`) 생성
  - PostgreSQL 확장을 위한 `CREATE EXTENSION` (`ltree`, `vector`, `pgcrypto`) 추가
- **Verification run**:
  - ✅ `docker exec meshboard-postgres psql -U meshboard -d meshboard -c "\dx"` → `ltree`, `vector` 익스텐션 활성화 확인
  - ✅ `docker exec meshboard-postgres psql -U meshboard -d meshboard -c "\dt"` → 18개 테이블 전체 생성 확인
  - ✅ FastAPI 서버(`curl http://localhost:8000/health`) → 정상 동작 유지 확인
- **Evidence captured**:
  - DB 테이블 18개 및 `ltree`, `vector` 확장 활성화 확인 완료
- **Commits**: `feat(PH1-db-001): 핵심 레지스트리 18개 테이블 스키마 및 마이그레이션 적용`
- **Files or artifacts updated**:
  - `backend/pyproject.toml`
  - `backend/app/models/__init__.py`
  - `backend/app/models/agent.py`, `workspace.py`, `policy.py`, `certification.py`, `conversation.py`, `message.py`, `interaction.py`, `notice.py`
  - `backend/alembic/versions/bd44babbb822_create_registry_tables.py`
  - `progress.md`, `feature_list.json`, `clean-state-checklist.md`
- **Known risk or unresolved issue**: 없음
- **Next best step**: `PH2-market-001` — 자연어 기반 에이전트 마켓플레이스 검색

### Session 003
- **Date**: 2026-04-24
- **Goal**: PH1-dash-001 — 홈 대시보드 및 타겟팅 공지 시스템 (NOTICES) 구현
- **Completed**:
  - `app/schemas/notice.py` 및 `app/api/v1/notices.py` 생성
  - 공지사항 생성(POST) 및 권한/만료일에 따른 조회(GET) 로직 구현
  - 프론트엔드 `tailwind.config.js`에 Apple 디자인 토큰(`apple-blue`, `apple-surface1` 등) 추가
  - `DashboardPage.tsx` 상단 Welcome 영역 및 Notices 카드에 Apple-style 디자인(`SF Pro` 기반 `font-apple`, 타이트한 행간/자간, 블랙 베이스) 적용
  - 테스트용 시드 스크립트로 3개 공지(전체, 운영자, 만료됨) 생성 완료
- **Verification run**:
  - ✅ 시드 스크립트로 공지 데이터 삽입 성공
  - ✅ 프론트엔드에서 공지사항 UI 정상 렌더링 확인 (타겟팅/만료 필터링)
- **Evidence captured**:
  - Dashboard UI에 Apple 스타일의 Notice 컴포넌트 추가됨
- **Commits**: `feat(PH1-dash-001): 공지사항 API 구현 및 대시보드 Apple-style 디자인 연동`
- **Files or artifacts updated**:
  - `backend/app/schemas/notice.py`, `backend/app/api/v1/notices.py`, `backend/app/main.py`
  - `frontend/src/api/notices.ts`
  - `frontend/tailwind.config.js`
  - `frontend/src/pages/DashboardPage.tsx`
  - `progress.md`, `feature_list.json`, `clean-state-checklist.md`
- **Known risk or unresolved issue**: 없음
- **Next best step**: `PH2-market-001` — 자연어 기반 에이전트 마켓플레이스 검색 구현

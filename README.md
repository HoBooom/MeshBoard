# MeshBoard

> 수천 개의 헤드리스 AI 에이전트를 기업 환경에서 발견·관리·운영·신뢰할 수 있도록 지원하는 통합 대시보드 플랫폼

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 서비스명 | **MeshBoard** |
| 목표 | 수천 개의 헤드리스 AI 에이전트를 기업 환경에서 발견·관리·운영·신뢰할 수 있도록 지원하는 통합 대시보드 플랫폼 |
| ERD | 18개 테이블, 5개 도메인 |
| 전체 일정 | 4개 Phase |
| 핵심 페르소나 | 사용자 · 개발자 · 운영자 · 거버넌스팀 |

## 2. 기술 스택

| 영역 | 기술 |
|------|------|
| **Frontend** | Vite + React 18 + TypeScript |
| **스타일링** | Tailwind CSS 3 |
| **라우팅** | React Router v6 |
| **API 클라이언트** | Axios (JWT 자동 첨부 인터셉터) |
| **상태 관리** | Zustand |
| **Backend** | FastAPI (Python 3.11+) |
| **ORM** | SQLAlchemy 2.0 (async) |
| **DB** | PostgreSQL 15 + pgvector (Docker) |
| **인증** | JWT (python-jose, HS256) + bcrypt |
| **마이그레이션** | Alembic |
| **패키지 관리** | uv (backend), npm (frontend) |

## 3. 사전 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 및 실행
- [uv](https://docs.astral.sh/uv/) 설치 (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 20+ 및 npm 설치

## 4. 실행 방법

### 4-1. 빠른 시작 (권장)

```bash
# 기본 시작: DB 기동 + 의존성 설치 + 마이그레이션
bash init.sh

# 시드 데이터 포함 시작
SEED_DB=1 bash init.sh

# 앱 전체 자동 시작 (Backend + Frontend 포함)
RUN_APP=1 bash init.sh

# 모두 포함
SEED_DB=1 RUN_APP=1 bash init.sh
```

### 4-2. 수동 단계별 실행

#### ① 인프라 기동 (PostgreSQL)

```bash
docker compose up -d

# 상태 확인
docker ps --filter "name=meshboard-postgres"
```

#### ② Backend 설정

```bash
cd backend

# 의존성 설치
uv sync

# DB 마이그레이션
uv run alembic upgrade head

# 시드 데이터 생성 (최초 1회)
uv run python -m app.seed

# 개발 서버 실행 (포트 8000)
uv run uvicorn app.main:app --reload --port 8000
```

#### ③ Frontend 설정

```bash
cd frontend

# 의존성 설치
npm install

# 개발 서버 실행 (포트 5173)
npm run dev
```

### 4-3. 접속 주소

| 서비스 | 주소 |
|--------|------|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API 문서 (Swagger) | http://localhost:8000/docs |
| API 문서 (ReDoc) | http://localhost:8000/redoc |

## 5. 데모 계정

> `SEED_DB=1 bash init.sh` 실행 후 사용 가능

| 이름 | 이메일 | 비밀번호 | 역할 |
|------|--------|----------|------|
| 관리자 | admin@meshboard.io | admin1234 | governance, trust_ops |
| 개발자 | dev@meshboard.io | dev1234 | agent_owner, agent_engineer |
| 운영자 | ops@meshboard.io | ops1234 | trust_ops, release_manager |
| 평가자 | user@meshboard.io | user1234 | evaluator |

## 6. 주요 API 엔드포인트

```bash
# 헬스체크
curl http://localhost:8000/health

# 로그인 (JWT 발급)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@meshboard.io","password":"admin1234"}'

# 내 정보 조회
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"

# RBAC 테스트 (governance/trust_ops 전용)
curl http://localhost:8000/api/v1/auth/admin-only \
  -H "Authorization: Bearer <access_token>"
```

## 7. 개발 규칙

- 한 번에 하나의 feature만 작업합니다 (`feature_list.json` 참고).
- feature 완료 조건: 구현 + 검증 실행 + `feature_list.json` / `progress.md` 업데이트 + 커밋.
- 세션 시작 전 반드시 `progress.md`를 확인합니다.
- 세션 종료 전 `clean-state-checklist.md`를 체크합니다.

## 8. DB 초기화 (개발 환경)

```bash
# 볼륨 포함 전체 초기화
docker compose down -v

# 재기동 + 마이그레이션 + 시드
docker compose up -d
cd backend && uv run alembic upgrade head && uv run python -m app.seed
```
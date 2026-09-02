# MeshBoard

> 조직 안의 AI 에이전트를 등록하고, 워크스페이스에 배치하고, 메시지·목표·정책·실행 상태를 한 화면에서 관리하는 Agent Mesh 운영 프로토타입

[![CI](https://github.com/INHAco2/MeshBoard_V2/actions/workflows/ci.yml/badge.svg)](https://github.com/INHAco2/MeshBoard_V2/actions/workflows/ci.yml)

## 프로젝트 범위

MeshBoard는 단일 챗봇이 아니라 여러 에이전트가 함께 일하는 환경을 운영하기 위한 포트폴리오 MVP입니다. 에이전트 등록부터 워크스페이스 배치, 메시지 라우팅, LangGraph 실행, 목표 단위 협업 관찰까지 하나의 흐름으로 연결합니다.

현재 검증된 핵심 범위는 다음과 같습니다.

- JWT/RBAC 기반 사용자·역할 관리
- 에이전트 메타데이터, 도구 allow-list, 구독 규칙 관리
- 워크스페이스 생성, 참여 요청, 에이전트 다중 배치
- `@mention` 및 subscription edge 기반 메시지 라우팅
- LangGraph 기반 `agent → tool → agent` 실행과 중단·재개
- Goal/Sub Goal과 전용 conversation 생성
- React Flow 기반 Agent Mesh 토폴로지
- CityLearn 전력 환경의 deterministic/LLM planner 및 CHESCA 시나리오 시각화
- 정책·인증 관리와 운영 콘솔의 기본 API/UI

정책의 런타임 강제 적용, durable checkpoint, 독립 worker queue, SSE/WebSocket, 불변 감사 저장소는 운영 확장 범위이며 아직 구현 완료로 주장하지 않습니다. 세부 상태는 [`feature_list.json`](./feature_list.json)을 기준으로 합니다.

## 아키텍처

```text
React + TypeScript
        │ REST/JWT
        ▼
FastAPI API ─────────────── PostgreSQL + pgvector
        │                         │
        ├─ Workspace / Goal       ├─ registry & RBAC
        ├─ Message Broker         ├─ message / receipt
        ├─ Trust / Operations     └─ interaction metadata
        │
        └─ LangGraph Runtime ── Tool allow-list ── Built-in / external tools
                    │
                    └─ CityLearn / CHESCA simulation runtime
```

에이전트 실행 시 등록된 도구 allow-list를 런타임에서도 검사합니다. 메시지 fan-out은 동시 실행 수와 개별 timeout을 제한합니다. 현재 LangGraph checkpoint는 프로세스 메모리 기반이므로 서버 재시작을 넘는 복구는 지원하지 않습니다. 자세한 설계와 경계는 [`backend/architecture.md`](./backend/architecture.md)를 참고하세요.

## 기술 스택

| 영역 | 구성 |
|---|---|
| Frontend | React 18, TypeScript 5.9, Vite 8, React Router 7 |
| Visualization | React Flow, Recharts, Tailwind CSS 3 |
| Backend | FastAPI, Python 3.11+, SQLAlchemy 2 async |
| Agent runtime | LangGraph, OpenAI-compatible API, MCP-shaped tool catalog |
| Data | PostgreSQL 15, pgvector, Alembic |
| Quality | unittest, ESLint 10, TypeScript strict mode, GitHub Actions |
| Package management | uv lockfile, npm lockfile |

## 빠른 시작

### 요구 사항

- Docker Desktop
- Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)
- Node.js 22.13 이상

```bash
git clone https://github.com/INHAco2/MeshBoard_V2.git
cd MeshBoard_V2
cp backend/.env.example backend/.env

# DB, locked dependencies, migration, tests, lint, build
./init.sh

# 데모 데이터까지 준비
SEED_DB=1 ./init.sh

# 준비 후 backend와 frontend 실행
SEED_DB=1 RUN_APP=1 ./init.sh
```

Docker 없이 코드 품질 게이트만 재현하려면 이미 의존성이 설치된 상태에서 다음을 실행합니다.

```bash
SKIP_DB=1 SKIP_INSTALL=1 ./init.sh
```

### 수동 실행

```bash
docker compose up -d --wait

cd backend
uv sync --locked
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload --port 8000
```

다른 터미널에서:

```bash
cd frontend
npm ci
npm run dev
```

| 서비스 | 주소 |
|---|---|
| Frontend | <http://localhost:5173> |
| API | <http://localhost:8000> |
| Swagger | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/health> |

## 데모 계정

`SEED_DB=1 ./init.sh` 실행 후 사용할 수 있는 로컬 전용 계정입니다.

| 역할 | 이메일 | 비밀번호 |
|---|---|---|
| Governance | `admin@meshboard.io` | `admin1234` |
| Agent developer | `dev@meshboard.io` | `dev1234` |
| Operator | `ops@meshboard.io` | `ops1234` |
| Evaluator | `user@meshboard.io` | `user1234` |

## 검증

```bash
cd backend
uv run python -m unittest discover -s tests -v

cd ../frontend
npm run lint
npm run build
npm audit --audit-level=high
```

GitHub Actions에서도 DB가 필요 없는 backend 37개 테스트와 frontend lint/build를 같은 방식으로 실행합니다.

## 저장소 구조

```text
backend/
  app/api/v1/          FastAPI route boundary
  app/core/            configuration, JWT, RBAC
  app/models/          SQLAlchemy registry models
  app/services/        agent runtime, broker, CityLearn services
  tests/               isolated API/service tests
frontend/
  src/api/             typed API clients
  src/pages/           dashboard workbenches
docs/                  experiments and operating notes
research/              reproducible research notebooks
CityLearn_old_system/  pinned simulation source used by the demo
Final_mesh1-main/      CHESCA experiment runtime used by the demo
```

`CityLearn_old_system`과 `Final_mesh1-main`은 재현을 위해 포함한 연구 런타임입니다. 애플리케이션 코드와 생성물은 분리하며 `node_modules`, `dist`, `pyc`, 로컬 환경 파일은 추적하지 않습니다.

## 보안 및 운영 주의사항

- `.env.example`만 커밋하고 실제 API key와 JWT secret은 커밋하지 않습니다.
- `ENVIRONMENT=production`에서는 기본 JWT secret과 wildcard CORS를 거부합니다.
- 외부 도구를 등록해도 각 에이전트에 명시적으로 허용된 도구만 실행할 수 있습니다.
- 현재 OIDC 구현은 provider boundary와 mock 검증용입니다. 실제 기업 IdP 연동 완료로 간주하지 않습니다.
- 현재 message broker는 bounded parallel execution이지만 독립 작업 큐는 아닙니다.

## 라이선스

MIT. 자세한 내용은 [`LICENSE`](./LICENSE)를 참고하세요.

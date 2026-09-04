# MeshBoard

> 조직 안의 AI 에이전트를 등록하고, 워크스페이스에 배치하고, 메시지·목표·정책·실행 상태를 한 화면에서 관리하는 Agent Mesh 운영 프로토타입

**Portfolio Release v1.0.0** · 설계 의도, 핵심 시연 흐름과 기술적 판단은 [`docs/portfolio-guide.md`](./docs/portfolio-guide.md)에 정리했습니다.

[![CI](https://github.com/HoBooom/MeshBoard/actions/workflows/ci.yml/badge.svg)](https://github.com/HoBooom/MeshBoard/actions/workflows/ci.yml)

## 프로젝트 범위

MeshBoard는 단일 챗봇이 아니라 여러 에이전트가 함께 일하는 환경을 운영하기 위한 포트폴리오 MVP입니다. 에이전트 등록부터 워크스페이스 배치, 메시지 라우팅, LangGraph 실행, 목표 단위 협업 관찰까지 하나의 흐름으로 연결합니다.

현재 검증된 핵심 범위는 다음과 같습니다.

- JWT/RBAC 기반 사용자·역할 관리
- 에이전트 메타데이터, 도구 allow-list, 구독 규칙 관리
- 워크스페이스 생성, 참여 요청, 에이전트 다중 배치
- `@mention`, subscription edge, 구독 규칙(도메인·intent·태그·우선순위) 기반 메시지 라우팅
- 명시적 agent ID/role 타기팅과 bounded parallel fan-out
- LangGraph 기반 `agent → tool → agent` 실행과 중단·재개
- Goal/Sub Goal과 전용 conversation 생성
- React Flow 기반 Agent Mesh 토폴로지
- CityLearn 전력 환경의 deterministic/LLM planner 및 CHESCA 시나리오 시각화
- 운영 데이터와 분리된 시나리오 Sandbox 및 의사결정 로그
- 정책 템플릿 검증, 실행 전 정책 강제, PII 마스킹, 인증 배지
- 운영자 Pause/Kill 신호, 두 진입점 모두에 남는 `ltree` 실행 트리, 모델별 토큰·병렬 실행 분석
- 보존 기간 기반 불변 감사 아카이브와 HMAC 서명 보안 웹훅
- interaction schema v1→v2 하위 호환 어댑터

durable checkpoint, 독립 worker queue, SSE/WebSocket과 실제 기업 IdP 연동은 운영 확장 범위이며 아직 구현 완료로 주장하지 않습니다. 세부 상태는 [`feature_list.json`](./feature_list.json)을 기준으로 합니다.

## 아키텍처

```text
React + TypeScript
        │ REST/JWT
        ▼
FastAPI API ─────────────── PostgreSQL + pgvector + ltree
        │                         │
        ├─ Workspace / Sandbox    ├─ registry & RBAC
        ├─ Message Broker         ├─ message / receipt
        ├─ Trust / Operations     ├─ execution tree / analytics
        └─ Archive / Webhook      └─ immutable archive
        │
        └─ LangGraph Runtime ── Tool allow-list ── Built-in / external tools
                    │
                    └─ CityLearn / CHESCA simulation runtime
```

에이전트 실행 시 활성 정책과 도구 allow-list를 런타임 경계에서 검사합니다. 메시지 fan-out은 동시 실행 수와 개별 timeout을 제한하며 모든 위임을 `ltree` 실행 트리로 기록합니다. 현재 LangGraph checkpoint와 Pause/Kill 신호는 프로세스 메모리 기반이므로 서버 재시작을 넘는 복구는 지원하지 않습니다. 자세한 설계와 경계는 [`backend/architecture.md`](./backend/architecture.md)를 참고하세요.

## 기술 스택

| 영역 | 구성 |
|---|---|
| Frontend | React 18, TypeScript 5.9, Vite 8, React Router 7 |
| Visualization | React Flow, Recharts, Tailwind CSS 3 |
| Backend | FastAPI, Python 3.11+, SQLAlchemy 2 async |
| Agent runtime | LangGraph, 로컬 OpenAI-호환 LLM(Ollama/Qwen 기본), MCP-shaped tool catalog |
| Data | PostgreSQL 15, pgvector, Alembic |
| Quality | unittest (123), ESLint 10, TypeScript strict mode, GitHub Actions |
| Package management | uv lockfile, npm lockfile |

## 빠른 시작

### 요구 사항

- Docker Desktop
- Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)
- Node.js 22.13 이상 — 셸 기본 버전이 낮아도 `nvm`/`fnm` 이 있으면 `./init.sh` 가 `.nvmrc` 버전을 스크립트 안에서만 활성화합니다(셸 설정은 건드리지 않음)
- [Ollama](https://ollama.com/download) + `ollama pull qwen3:8b` — 에이전트 실행용 **로컬** 모델

> 에이전트 실행은 기본적으로 로컬 모델만 사용합니다. **API 키가 필요 없고 유료 호출도 발생하지 않습니다.**
> Ollama가 없어도 DB·API·보드·테스트는 모두 동작하며, 에이전트를 실제로 invoke 할 때만 필요합니다.

```bash
git clone https://github.com/HoBooom/MeshBoard.git
cd MeshBoard
./init.sh
```

`./init.sh` 하나가 전부를 처리합니다 — `backend/.env` 생성, PostgreSQL 기동, 잠긴 의존성 설치,
마이그레이션, **backend 테스트 123개**, frontend lint/build/audit, 그리고 스택이 실제로
붙어서 동작하는지 확인하는 end-to-end 검증까지 순서대로 실행합니다.

| 변형 | 하는 일 |
|---|---|
| `PULL_MODEL=1 ./init.sh` | 로컬 모델(`qwen3:8b`)까지 자동으로 내려받습니다 |
| `SEED_DB=1 ./init.sh` | 데모 계정·공지·정책 시드까지 넣습니다 |
| `SEED_DB=1 RUN_APP=1 ./init.sh` | 위를 마친 뒤 backend·frontend를 띄웁니다 |
| `SKIP_DB=1 SKIP_INSTALL=1 ./init.sh` | Docker 없이 코드 품질 게이트만 재현합니다 |
| `SKIP_VERIFY=1 ./init.sh` | 검증을 건너뛰고 환경만 준비합니다 |

Ollama나 Docker가 없어도 중단되지 않습니다. 쓸 수 없는 검증은 이유를 출력하고 건너뜁니다
(통합 테스트는 DB가 없으면 스스로 skip합니다). `npm audit` 은 레지스트리 장애로 셋업 전체가
막히지 않도록 결과만 알리고 진행합니다.

### 수동 실행

```bash
docker compose up -d --wait
ollama pull qwen3:8b       # 에이전트 실행용 로컬 모델 (최초 1회)
cp backend/.env.example backend/.env

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
./init.sh
```

검증은 위 한 줄이면 됩니다. 개별로 돌리려면:

```bash
cd backend && uv run python -m unittest discover -s tests -v
cd ../frontend && npm run lint && npm run build && npm audit --audit-level=high
```

backend 테스트 **123개**는 두 층으로 나뉩니다.

| 층 | 개수 | 대상 |
|---|---:|---|
| 단위·계약 | 82 | 정책 평가, 구독 규칙, 도구 경계, LLM 백엔드 설정, 스키마 |
| 통합 (PostgreSQL) | 41 | 브로커 라우팅, ltree 실행 트리, 토큰·병렬 집계, JWT/RBAC 강제, 발신자 위조 차단 |

통합 테스트는 실제 PostgreSQL에 붙습니다(ltree·JSONB·ARRAY를 쓰므로 대체 불가). 각 테스트는
트랜잭션 안에서 실행되고 롤백되므로 DB에 흔적이 남지 않으며, DB가 없으면 **조용히 skip**되어
`docker compose up -d` 없이도 위 명령이 그대로 통과합니다. GitHub Actions는 postgres 서비스를
띄워 통합 테스트까지 전부 실행합니다.

`./init.sh` 는 마지막에 스택 end-to-end 검증도 실행합니다. 따로 돌리려면:

```bash
uv run --project backend python backend/scripts/verify_local_stack.py
```

로컬 LLM 연결 → LangGraph 도구 실행 → 브로커 라우팅 → 실행 트리 → 토큰·병렬 집계를 순서대로
실행하고 결과를 출력합니다(DB 변경은 롤백).

## 성능 평가와 재현

플랫폼 위에서 건물별 에이전트가 ESS 충·방전을 협의하는 시나리오를 CityLearn 환경으로 평가했습니다.
아래는 `backend/scripts/exp_v2.py` 실행 결과이며, 원시 값은 [`docs/_exp_v2_checkpoint.json`](./docs/_exp_v2_checkpoint.json)에
있습니다. 자세한 설계와 해석은 [`docs/CityLearn_MacroMesh_v2_Experiment.md`](./docs/CityLearn_MacroMesh_v2_Experiment.md)를 참고하세요.

| 실험 (H=15) | noctrl | SAC-RBC | mesh v1 | **mesh v2** |
|---|---:|---:|---:|---:|
| 정상 17빌딩 · 소비(kWh) | 251.9 | 245.5 | 250.6 | **233.4** |
| 돌발 부하 shock · 소비(kWh) | 435.6 | 429.1 | 429.8 | **418.2** |
| 빌딩 추가 19빌딩 · 소비(kWh) | 287.6 | **실행 실패** | 314.9 | **267.9** |

핵심은 세 번째 행입니다. 건물이 17→19로 늘자 학습된 SAC-RBC는 번들 로드에 실패하고 대체 RBC마저
`IndexError`로 죽었지만, LLM 협상 구조는 **코드 변경 없이** 동작하며 무제어 대비 6.8%, v1 대비 14.9%
낮은 소비를 유지했습니다. v1은 오히려 무제어보다 악화(314.9 > 287.6)돼 에이전트 증가 시 조정이
무너졌고, v2의 rollout 검증과 Introspector가 이를 막았습니다.

> **지표 주의**: 위 개선은 단지 소비·피크·Reward 기준입니다. CityLearn 공식 challenge KPI는 ramping
> 평활성을 중시하므로 v2의 공격적 방전과 상충하며, 정상 시나리오에서는 v2가 baseline보다 높습니다
> (1.190 vs 1.000). 이 텐션은 실험 문서 §5에 그대로 기록했습니다.

```bash
# 위 표 재현 (LLM 협상 모드는 로컬 모델이 필요합니다)
uv run --project backend python backend/scripts/exp_v2.py \
  --start 4200 --horizon 15 --soc 0.5 --dummies 2 --shock-mult 2.0 \
  --exps normal,disturbance,building_add --modes noctrl,sarbc,macro_v1,macro_v2

# 모드별 CityLearn KPI 평가 (noctrl/sarbc/deterministic은 LLM 없이 실행)
uv run --project backend python backend/scripts/eval_modes.py \
  --modes noctrl,sarbc,deterministic --horizons "5,20,40" \
  --datasets citylearn_challenge_2022_phase_all
```

## 저장소 구조

```text
backend/
  app/api/v1/          FastAPI route boundary
  app/core/            configuration, JWT, RBAC
  app/models/          SQLAlchemy registry models
  app/services/        runtime, broker, policy, archive, connector services
  tests/               isolated API/service tests
frontend/
  src/api/             typed API clients
  src/pages/           dashboard workbenches
docs/                  experiments and operating notes
research/              reproducible research notebooks
CityLearn_old_system/  pinned CityLearn runtime + 실제 사용하는 데이터셋 9개만 유지
Final_mesh1-main/      CHESCA experiment runtime + 집계 결과(요약 CSV)
```

`CityLearn_old_system`과 `Final_mesh1-main`은 성능 수치를 재현하기 위해 포함한 연구 런타임입니다.
실행에 필요한 것만 남겨 저장소를 약 70MB로 유지합니다 — 미사용 데이터셋, 업스트림 이미지 asset,
원시 메시지 로그(`mesh_messages.csv`)는 제거했으며 집계 결과와 실험 체크포인트는 근거로 남겨두었습니다.
`node_modules`, `dist`, `pyc`, 로컬 환경 파일은 추적하지 않습니다.

## 보안 및 운영 주의사항

- 에이전트 실행은 기본적으로 **로컬 모델만** 사용합니다. 외부 게이트웨이는 `RUNYOUR_API_KEY`를 채웠을 때만 활성화되며, 비어 있으면 어떤 유료 호출도 나가지 않습니다.
- `.env.example`만 커밋하고 실제 API key와 JWT secret은 커밋하지 않습니다.
- `ENVIRONMENT=production`에서는 기본 JWT secret과 wildcard CORS를 거부합니다.
- 외부 도구를 등록해도 각 에이전트에 명시적으로 허용된 도구만 실행할 수 있습니다.
- 활성 정책은 실행 전에 차단어·입력 길이·필수 인증·도구 범위를 강제하며 선택적으로 PII를 마스킹합니다.
- 보안 정책 위반 이벤트는 설정 시 HMAC-SHA256 서명 웹훅으로 전달됩니다.
- 아카이브 레코드는 PostgreSQL trigger가 UPDATE/DELETE를 거부합니다.
- 인증은 자체 JWT/RBAC 만 제공합니다. 기업 IdP(OIDC) 연동은 구현 범위에 포함하지 않았습니다.
- 현재 message broker는 bounded parallel execution이지만 독립 작업 큐는 아닙니다.

## 라이선스

MIT. 자세한 내용은 [`LICENSE`](./LICENSE)를 참고하세요.

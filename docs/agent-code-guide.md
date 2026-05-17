# MeshBoard — Agent 코드 분석 가이드

> **Feature**: `PH3-creator-001` 에이전트 메타데이터 등록 및 구독 편집기  
> **작성일**: 2026-04-26  
> **대상 독자**: 이 코드를 처음 읽거나 확장하려는 개발자

---

## 목차

1. [전체 아키텍처 개요](#1-전체-아키텍처-개요)
2. [파일 구조 맵](#2-파일-구조-맵)
3. [데이터 흐름 — 에이전트 등록](#3-데이터-흐름--에이전트-등록)
4. [데이터 흐름 — 에이전트 실행(invoke)](#4-데이터-흐름--에이전트-실행invoke)
5. [핵심 파일 분석](#5-핵심-파일-분석)
   - [5-1. config.py — 환경 설정](#5-1-configpy--환경-설정)
   - [5-2. schemas/agent.py — Pydantic 스키마](#5-2-schemasagentpy--pydantic-스키마)
   - [5-3. services/tool_catalog.py — MCP 도구 레지스트리](#5-3-servicestool_catalogpy--mcp-도구-레지스트리)
   - [5-4. services/agent_runtime.py — ReAct 루프 엔진](#5-4-servicesagent_runtimepy--react-루프-엔진)
   - [5-5. api/v1/agents.py — REST API 라우터](#5-5-apiv1agentspy--rest-api-라우터)
   - [5-6. frontend/api/agents.ts — 프론트엔드 API 클라이언트](#5-6-frontendapiagentsts--프론트엔드-api-클라이언트)
   - [5-7. frontend/pages/CreatorPage.tsx — UI 컴포넌트](#5-7-frontendpagesCreatorPagetsx--ui-컴포넌트)
6. [텍스트 기반 ReAct 루프 설계 이유](#6-텍스트-기반-react-루프-설계-이유)
7. [Pydantic × SQLAlchemy metadata 충돌 해결법](#7-pydantic--sqlalchemy-metadata-충돌-해결법)
8. [새 도구(MCP) 추가하는 방법](#8-새-도구mcp-추가하는-방법)
9. [API 명세 Quick Reference](#9-api-명세-quick-reference)
10. [알려진 한계 및 확장 포인트](#10-알려진-한계-및-확장-포인트)

---

## 1. 전체 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (React)                                            │
│  ┌──────────────────┐   ┌─────────────────────────────────┐ │
│  │  CreatorPage.tsx │──▶│  frontend/src/api/agents.ts     │ │
│  └──────────────────┘   └────────────────┬────────────────┘ │
└───────────────────────────────────────────┼─────────────────┘
                                            │ HTTP / Axios
┌───────────────────────────────────────────▼─────────────────┐
│  FastAPI Backend                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  api/v1/agents.py  (APIRouter)                       │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────┐ │  │
│  │  │  CRUD    │  │ Subscription │  │  /invoke       │ │  │
│  │  │ /agents  │  │    Rule      │  │  (실행 테스트) │ │  │
│  │  └────┬─────┘  └──────┬───────┘  └───────┬────────┘ │  │
│  └───────┼────────────────┼──────────────────┼──────────┘  │
│          │ SQLAlchemy ORM │                  │              │
│  ┌───────▼────────────────▼──┐  ┌────────────▼──────────┐  │
│  │   PostgreSQL              │  │  agent_runtime.py     │  │
│  │  AGENTS                   │  │  (텍스트 ReAct 루프)  │  │
│  │  AGENT_SUBSCRIPTION_RULES │  └────────────┬──────────┘  │
│  └───────────────────────────┘               │              │
│                                   ┌──────────▼──────────┐  │
│                                   │  tool_catalog.py    │  │
│                                   │  (내장 MCP 5종)     │  │
│                                   └──────────┬──────────┘  │
└──────────────────────────────────────────────┼─────────────┘
                                               │ OpenAI SDK
                                    ┌──────────▼──────────┐
                                    │  RunYour AI          │
                                    │  (openai/gpt-5)      │
                                    └─────────────────────┘
```

---

## 2. 파일 구조 맵

```
meshboard/
├── backend/
│   ├── .env                          # RUNYOUR_API_KEY 등 시크릿
│   └── app/
│       ├── core/
│       │   └── config.py             # ① 환경 변수 / LLM 설정
│       ├── models/
│       │   └── agent.py              # SQLAlchemy ORM 모델
│       ├── schemas/
│       │   └── agent.py              # ② Pydantic 입출력 스키마
│       ├── services/
│       │   ├── tool_catalog.py       # ③ 내장 MCP 도구 정의
│       │   └── agent_runtime.py      # ④ ReAct 루프 실행 엔진
│       └── api/v1/
│           └── agents.py             # ⑤ REST API 엔드포인트
└── frontend/src/
    ├── api/
    │   └── agents.ts                 # ⑥ Axios API 래퍼 + TS 타입
    └── pages/
        └── CreatorPage.tsx           # ⑦ UI 페이지 (목록+편집+실행)
```

---

## 3. 데이터 흐름 — 에이전트 등록

```
UI (CreatorPage)
  │  formToCreatePayload(form)
  │  → { name, version, tools: [...], agent_card: {system_prompt}, 
  │       subscription_rule: {...} }
  │
  ▼  POST /api/v1/agents
API Router (agents.py)
  │  1. _ensure_valid_agent_payload()  — status/visibility 검증
  │  2. _ensure_valid_tools()          — TOOL_REGISTRY 에 없으면 422
  │  3. 중복 이름 검사 (SELECT → 409 if exists)
  │  4. Agent ORM 생성 → db.add(agent) → await db.flush()
  │  5. subscription_rule 포함 시 AgentSubscriptionRule ORM 생성
  │  6. await db.refresh() → _agent_to_read() → JSON 응답
  │
  ▼  PostgreSQL
AGENTS 테이블
  agent_id (UUID PK)
  name, version, purpose, description, approach
  owner_id (FK → users)
  status   : DRAFT | ACTIVE | DEPRECATED | SUSPENDED
  visibility : PRIVATE | DEPARTMENT | PUBLIC
  agent_card : JSONB  { system_prompt?: string, ... }
  roles      : TEXT[]
  collaborators : TEXT[]
  tools      : TEXT[]   ← MCP 도구 ID 목록
  metadata   : JSONB  { category?: string, ... }
  created_at, updated_at : TIMESTAMPTZ

AGENT_SUBSCRIPTION_RULES 테이블 (에이전트당 1행)
  rule_id   (UUID PK)
  agent_id  (FK → agents)
  watch_domains  : TEXT[]
  watch_intents  : TEXT[]
  watch_tags     : TEXT[]
  watch_senders  : UUID[]
  watch_roles    : TEXT[]
  ignore_senders : UUID[]
  ignore_tags    : TEXT[]
  min_priority : low | medium | high | critical
  is_active    : BOOLEAN
  updated_at   : TIMESTAMPTZ
```

---

## 4. 데이터 흐름 — 에이전트 실행(invoke)

```
UI (CreatorPage — 섹션 5)
  │  invokeMessage (사용자 입력 텍스트)
  │
  ▼  POST /api/v1/agents/{agent_id}/invoke
  │  { "message": "E001 사번의 연차 잔여일을 알려줘" }
  │
API Router
  │  _load_owned_agent()  → Agent ORM 로드
  │  invoke_agent(agent, message) 호출
  │
  ▼  agent_runtime.py
  │
  ├─ _build_system_prompt(agent)
  │    ├─ agent_card.system_prompt 있으면 그대로 사용
  │    └─ 없으면 name/purpose/approach/description/roles 조합
  │    + _build_tool_manifest(agent.tools)  ← 도구 설명 텍스트 생성
  │    + 응답 프로토콜 규칙 주입
  │       ┌─────────────────────────────────────────┐
  │       │ {"action":"tool","tool":"<id>","arguments":{...}} │
  │       │ {"action":"final","answer":"<한국어 답변>"}      │
  │       └─────────────────────────────────────────┘
  │
  ├─ [ReAct 루프 — 최대 MAX_TOOL_STEPS(=6)회]
  │    │
  │    ├─ LLM 호출 (openai.OpenAI.chat.completions.create)
  │    │
  │    ├─ _extract_json(raw_content)
  │    │    ├─ 파싱 실패 → 텍스트 그대로 final_output 으로 반환
  │    │    └─ 파싱 성공
  │    │         ├─ action == "final" → final_output 확정, 루프 종료
  │    │         └─ action == "tool"
  │    │              ├─ _call_tool(tool_id, arguments)
  │    │              │    └─ TOOL_REGISTRY[tool_id].invoke(arguments)
  │    │              └─ observation 을 user 메시지로 대화에 추가
  │    │                   → 다음 루프 이터레이션
  │    └─ [루프 종료]
  │
  ▼  InvokeResponse 반환
  {
    "agent_id": "...",
    "agent_name": "...",
    "model_used": "openai/gpt-5",
    "input": "E001 사번의 연차 잔여일을 알려줘",
    "output": "김하늘 님의 남은 연차는 11일이며...",
    "tool_calls": [{"name": "lookup_employee_leave", "args": {"employee_id": "E001"}}],
    "steps": [...],   ← 전체 메시지 로그 (디버그용)
    "error": null
  }
```

---

## 5. 핵심 파일 분석

### 5-1. `config.py` — 환경 설정

```
backend/app/core/config.py
```

**LLM 관련 3가지 변수**

| 변수 | 기본값 | 역할 |
|------|--------|------|
| `RUNYOUR_API_KEY` | `""` | `.env` 에서 주입. RunYour AI API 키 |
| `RUNYOUR_BASE_URL` | `https://api.runyour.ai/v1` | OpenAI-호환 엔드포인트 URL |
| `DEFAULT_LLM_MODEL` | `openai/gpt-5-mini` | invoke 시 모델 미지정 시 사용 |

> **주의**: `RUNYOUR_API_KEY` 가 빈 문자열이면 `invoke_agent` 호출 시 `RuntimeError` 가 발생합니다.

---

### 5-2. `schemas/agent.py` — Pydantic 스키마

```
backend/app/schemas/agent.py
```

#### 스키마 종류와 용도

| 클래스 | 방향 | 설명 |
|--------|------|------|
| `AgentCreate` | Request | 에이전트 신규 등록 (`POST /agents`) |
| `AgentUpdate` | Request | 에이전트 부분 수정 (`PUT /agents/{id}`) |
| `AgentRead` | Response | 목록·상세 응답 |
| `SubscriptionRuleCreate` | Request | 구독 규칙 생성/수정 |
| `SubscriptionRuleRead` | Response | 구독 규칙 조회 |
| `ToolDescriptor` | Response | 도구 카탈로그 항목 |
| `InvokeRequest` | Request | 에이전트 실행 요청 |
| `InvokeResponse` | Response | 에이전트 실행 결과 |

#### `metadata_` 필드의 특수 처리

SQLAlchemy의 `DeclarativeBase` 내부적으로 `metadata` 속성을 사용하기 때문에  
ORM 모델에서 컬럼 이름을 `metadata_`(언더스코어 접미사)로 정의합니다.  
이 불일치를 Pydantic 레벨에서 두 방향으로 해소합니다.

```
─── 입력(Request) ───────────────────────────────────────────
AgentCreate / AgentUpdate:
  metadata_ = Field(
      validation_alias=AliasChoices("metadata", "metadata_"),
      serialization_alias="metadata",
  )
  → JSON 요청에서 "metadata" 로 보내면 내부적으로 metadata_ 에 매핑
  → JSON 직렬화 시 "metadata" 키로 출력

─── 출력(Response) ──────────────────────────────────────────
AgentRead:
  metadata_: Dict[str, Any]
  → ORM 속성 이름 그대로 노출 (from_attributes=True 로 매핑)
  → 클라이언트는 "metadata_" 키로 읽음
```

> **왜 AgentRead 만 다른가?** 응답에서는 ORM 인스턴스를 직접 `model_validate` 하기 때문에 alias 없이 속성 이름을 그대로 사용합니다.

---

### 5-3. `services/tool_catalog.py` — MCP 도구 레지스트리

```
backend/app/services/tool_catalog.py
```

#### 구조

```python
@lc_tool                          # langchain_core 데코레이터
def lookup_employee_leave(employee_id: str) -> str:
    """독스트링이 LLM 에게 노출되는 도구 설명입니다."""
    ...

TOOL_REGISTRY: Dict[str, BaseTool] = {
    "lookup_employee_leave": lookup_employee_leave,
    ...
}

TOOL_CATALOG: List[Dict] = [
    {"id": "lookup_employee_leave", "name": "직원 연차 조회 (데모)", "description": "..."},
    ...
]
```

- **`TOOL_REGISTRY`**: 런타임에서 `tool.invoke(args)` 로 실제 실행하는 객체 맵
- **`TOOL_CATALOG`**: UI 에 표시하고 API 로 내려보내는 메타데이터 리스트

#### 현재 등록된 기본 도구

| ID | 이름 | 설명 |
|----|------|------|
| `get_current_time` | 현재 시각 조회 | UTC ISO 8601 반환 |
| `echo` | 에코(Echo) | 입력 그대로 반환 (테스트용) |
| `calculate` | 수식 계산 | `ast` 기반 안전한 수식 평가 |
| `advanced_calculate` | 고급 수학 계산 | `sqrt`, `sin`, `log`, `pi` 등 수학 함수/상수 지원 |
| `web_search` | 웹 검색 | 외부 웹 검색 결과를 제목, URL, 요약으로 반환 |
| `fetch_url` | URL 본문 조회 | HTTP/HTTPS URL 본문을 가져와 텍스트로 반환 |
| `lookup_employee_leave` | 직원 연차 조회 (데모) | E001~E003 고정 Mock 데이터 |
| `search_knowledge_base` | 사내 지식베이스 검색 (데모) | 키워드 매칭 FAQ 반환 |

#### 환경변수 기반 외부 HTTP MCP 도구

`EXTERNAL_MCP_TOOLS` 에 JSON 배열을 넣으면 서버 시작 시 `TOOL_REGISTRY` 와 UI 카탈로그에 외부 도구가 동적으로 추가됩니다.

```json
[
  {
    "id": "company_search",
    "name": "회사 검색 API",
    "description": "사내 검색 API를 호출합니다.",
    "url": "https://example.com/mcp/search",
    "method": "POST",
    "headers": {"Authorization": "Bearer token"},
    "inputSchema": {
      "type": "object",
      "properties": {"query": {"type": "string"}},
      "required": ["query"]
    }
  }
]
```

`method` 는 `GET` 또는 `POST` 를 지원합니다. `POST` 는 에이전트가 넘긴 arguments 를 JSON body 로 보내고, `GET` 은 query parameter 로 보냅니다.

---

### 5-4. `services/agent_runtime.py` — ReAct 루프 엔진

```
backend/app/services/agent_runtime.py
```

가장 핵심적인 파일입니다. 총 5개의 함수로 구성됩니다.

#### 함수 역할 요약

```
_build_tool_manifest(tool_ids)
  └─ tool_ids 로 TOOL_CATALOG + TOOL_REGISTRY 에서 메타데이터 조회
  └─ LLM 이 읽을 수 있는 텍스트 형식으로 직렬화
      - id, name, description, arguments(JSON 스키마)

_build_system_prompt(agent)
  └─ agent_card.system_prompt 가 있으면 그것을 페르소나로 사용
  └─ 없으면 name/purpose/approach/description/roles 로 자동 생성
  └─ 도구 매니페스트 + 응답 프로토콜 규칙 추가

_build_openai_client()
  └─ settings.RUNYOUR_API_KEY + settings.RUNYOUR_BASE_URL 로
     openai.OpenAI 인스턴스 생성

_extract_json(raw)
  └─ LLM 응답에서 JSON 추출 (3단계 시도)
      1. 직접 json.loads
      2. ```json ... ``` 코드블록 제거 후 재시도
      3. 정규식으로 {...} 패턴 추출 후 재시도
  └─ 모두 실패하면 None 반환

_call_tool(tool_id, arguments)
  └─ TOOL_REGISTRY[tool_id].invoke(arguments)
  └─ 반환값을 항상 str 로 변환

invoke_agent(agent, user_message, model)  ← 진입점
  └─ 위 헬퍼들을 조합해 ReAct 루프 실행
  └─ 결과: {model_used, output, tool_calls, steps, error}
```

#### ReAct 루프 상태 머신

```
초기화: messages = [system, user]

─── for step_idx in range(MAX_TOOL_STEPS=6): ───────────────────

  ┌─ LLM 호출 → raw_content ─────────────────────────────────┐
  │                                                           │
  │  _extract_json(raw_content)                               │
  │         │                                                 │
  │  None ──┴──▶ final_output = raw_content, break           │
  │         │                                                 │
  │  action == "final" ──▶ final_output = answer, break       │
  │         │                                                 │
  │  action == "tool"                                         │
  │      │                                                    │
  │      ├─ _call_tool(tool_id, arguments) → observation      │
  │      ├─ steps.append({role:"tool", ...})                  │
  │      └─ messages.append({role:"user",                     │
  │             content: "도구 실행 결과:\n{observation}\n..."})│
  │                              │                            │
  │                              └─ continue (다음 이터레이션) │
  └───────────────────────────────────────────────────────────┘

else (루프 소진):
  final_output = "(최대 도구 호출 횟수 초과...)"
```

---

### 5-5. `api/v1/agents.py` — REST API 라우터

```
backend/app/api/v1/agents.py
```

#### 헬퍼 함수 4종

```python
_ensure_valid_agent_payload(status, visibility)  # enum 검증
_ensure_valid_tools(tool_ids)                    # TOOL_REGISTRY 존재 확인
_ensure_valid_rule(rule)                         # min_priority 검증
_get_rule_for_agent(db, agent_id)                # DB에서 구독 규칙 SELECT
_agent_to_read(agent, rule)                      # ORM → AgentRead 변환
_load_owned_agent(db, agent_id, user)            # 소유권 체크 포함 로드
```

#### 엔드포인트 목록

| Method | Path | 설명 | 권한 |
|--------|------|------|------|
| `GET` | `/agents/tools` | 도구 카탈로그 조회 | 인증 필요 |
| `GET` | `/agents` | 내 에이전트 목록 | 소유자 |
| `POST` | `/agents` | 에이전트 신규 등록 | 인증 필요 |
| `GET` | `/agents/{id}` | 에이전트 상세 | 소유자 or PUBLIC |
| `PUT` | `/agents/{id}` | 에이전트 수정 | 소유자 |
| `GET` | `/agents/{id}/subscription-rule` | 구독 규칙 조회 | 소유자 |
| `PUT` | `/agents/{id}/subscription-rule` | 구독 규칙 upsert | 소유자 |
| `POST` | `/agents/{id}/invoke` | 에이전트 실행 테스트 | 소유자 |

#### `create_agent` 의 트랜잭션 패턴

```python
# flush (DB 반영, 커밋 X) → agent_id 확보
db.add(agent)
await db.flush()

# agent_id 를 FK 로 구독 규칙 생성
db.add(rule)
await db.flush()

# 최신 상태 리로드
await db.refresh(agent)
await db.refresh(rule)
```

> `flush` 를 두 번 쓰는 이유: `agent_id` (자동 생성 UUID) 가 확정된 뒤에야  
> `AgentSubscriptionRule` 의 FK 를 채울 수 있기 때문입니다.  
> 두 객체가 동일한 트랜잭션 안에 있으므로 에러 시 함께 롤백됩니다.

---

### 5-6. `frontend/api/agents.ts` — 프론트엔드 API 클라이언트

```
frontend/src/api/agents.ts
```

#### 주요 타입

```typescript
// 에이전트 응답 타입 (AgentRead 대응)
interface Agent {
  agent_id: string;
  metadata_: Record<string, unknown>;  // ← 응답에서는 "metadata_" 키
  tools: string[];                      // MCP tool ID 배열
  subscription_rule?: SubscriptionRule | null;
  ...
}

// 생성/수정 요청 타입
interface AgentCreatePayload {
  metadata?: Record<string, unknown>;  // ← 요청에서는 "metadata" 키
  tools?: string[];
  ...
}
```

> `Agent.metadata_` vs `AgentCreatePayload.metadata` 의 키 이름 차이에 주의하세요.  
> 백엔드 스키마의 alias 설계를 그대로 반영한 것입니다.

#### agentsApi 메서드 목록

```typescript
agentsApi.listTools()                              // GET /agents/tools
agentsApi.listMyAgents()                           // GET /agents
agentsApi.getAgent(agentId)                        // GET /agents/{id}
agentsApi.createAgent(payload)                     // POST /agents
agentsApi.updateAgent(agentId, payload)            // PUT /agents/{id}
agentsApi.getSubscriptionRule(agentId)             // GET /agents/{id}/subscription-rule
agentsApi.upsertSubscriptionRule(agentId, rule)    // PUT /agents/{id}/subscription-rule
agentsApi.invokeAgent(agentId, message, model?)    // POST /agents/{id}/invoke
```

---

### 5-7. `frontend/pages/CreatorPage.tsx` — UI 컴포넌트

```
frontend/src/pages/CreatorPage.tsx
```

#### 컴포넌트 구조

```
CreatorPage (기본 export)
  ├─ 상태: agents, tools, editorMode, activeAgent, form, invokeResult ...
  ├─ loadAll()        — /agents + /tools 병렬 fetch
  ├─ openCreate()     — editorMode = 'create', form = EMPTY_FORM
  ├─ openEdit(agent)  — editorMode = 'edit', getSubscriptionRule 호출 후 form 채움
  ├─ handleSave()     — create: createAgent() / edit: updateAgent() + upsertSubscriptionRule()
  ├─ handleInvoke()   — invokeAgent() 호출 → invokeResult 저장
  │
  ├─ [에이전트 카드 그리드]
  └─ AgentEditor (editorMode != 'closed' 일 때 렌더)
       ├─ Section "1. 기본 정보"
       ├─ Section "2. 에이전트 자질 (프롬프트 & 설명)"
       ├─ Section "3. 도구 (MCP) 선택"
       ├─ Section "4. 구독 규칙"
       └─ Section "5. 실행 테스트" (edit 모드에서만 표시)

Section({ title, children })  — 섹션 레이아웃 래퍼
Field({ label, required, children })  — 라벨 + 입력 래퍼
```

#### 중요 유틸 함수 3종

```typescript
// Agent ORM → FormState 변환 (편집 모달 열기 시 사용)
agentToForm(agent, rule): FormState

// FormState → POST /agents 페이로드 변환
formToCreatePayload(form): AgentCreatePayload

// FormState → PUT /agents/{id} + PUT .../subscription-rule 페이로드 변환
formToUpdatePayload(form): AgentUpdatePayload
formToRulePayload(form): Partial<SubscriptionRule>
```

---

## 6. 텍스트 기반 ReAct 루프 설계 이유

OpenAI function-calling(구조적 `tool_calls` 응답)을 쓰지 않고 텍스트 JSON 프로토콜을 선택한 이유:

| 문제 | 원인 | 해결 |
|------|------|------|
| `tool_calls: null` 반환 | RunYour AI 프록시가 GPT-5 계열의 function-calling 응답을 일관되게 전달하지 못함 | LLM 이 직접 `{"action":"tool",...}` JSON 텍스트를 출력하도록 system prompt 에서 프로토콜 명시 |
| `image_gen` tool 자동 주입 | RunYour 프록시가 tools 배열에 내부 도구를 추가함 | tools 파라미터 자체를 사용하지 않으므로 영향 없음 |
| langchain `create_react_agent` 미동작 | 위 두 문제의 복합 영향 | openai SDK 직접 호출로 대체 |

> **향후 전환 경로**: 표준 OpenAI API(`api.openai.com`)로 바꾸면  
> `tool_calls` 가 정상 동작하므로 `agent_runtime.py` 의  
> `invoke_agent` 를 langchain `create_react_agent` 기반으로 교체 가능합니다.  
> `TOOL_REGISTRY` 가 langchain `BaseTool` 기반이므로 그대로 재사용할 수 있습니다.

---

## 7. Pydantic × SQLAlchemy `metadata` 충돌 해결법

SQLAlchemy 의 `DeclarativeBase` 는 클래스 수준에서 `metadata` 속성을 예약합니다.  
동일한 이름의 컬럼을 정의하면 Pydantic 직렬화 시 `MetaData` 객체가 노출되어  
`Input should be a valid dictionary` 오류가 발생합니다.

**해결 방법**: ORM 컬럼 이름을 `metadata_` 로 정의하고 Pydantic 에서 alias 로 대응

```python
# models/agent.py
class Agent(Base):
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, ...)
    #           ↑ Python 속성명    ↑ DB 컬럼명

# schemas/agent.py — 요청 스키마
class AgentCreate(BaseModel):
    metadata_: Dict = Field(
        validation_alias=AliasChoices("metadata", "metadata_"),
        # JSON {"metadata": {...}} 또는 {"metadata_": {...}} 모두 허용
        serialization_alias="metadata",
        # 직렬화 시 "metadata" 로 출력
    )

# schemas/agent.py — 응답 스키마
class AgentRead(BaseModel):
    metadata_: Dict  # ORM 속성명 그대로 (from_attributes=True)
    model_config = ConfigDict(from_attributes=True)
```

---

## 8. 새 도구(MCP) 추가하는 방법

정적 내장 도구는 `backend/app/services/tool_catalog.py` 파일에서 세 곳을 수정합니다.

**Step 1.** 함수 구현 (langchain `@lc_tool` 데코레이터 필수)

```python
@lc_tool
def my_new_tool(param1: str, param2: int = 0) -> str:
    """이 도구가 하는 일을 한 문장으로 설명하세요. LLM 에게 노출됩니다.

    Args:
        param1: 첫 번째 파라미터 설명.
        param2: 두 번째 파라미터 설명.
    """
    return f"결과: {param1}, {param2}"
```

**Step 2.** `TOOL_REGISTRY` 에 등록

```python
TOOL_REGISTRY: Dict[str, BaseTool] = {
    ...
    "my_new_tool": my_new_tool,   # ← 추가
}
```

**Step 3.** `TOOL_CATALOG` 에 UI 메타데이터 등록

```python
TOOL_CATALOG: List[Dict[str, str]] = [
    ...
    {
        "id": "my_new_tool",
        "name": "새 도구 이름",
        "description": "UI 카드에 표시될 짧은 설명.",
    },
]
```

> 세 곳 모두 추가하면 서버 재시작 없이(uvicorn `--reload` 모드 기준) UI 의  
> "도구(MCP) 선택" 섹션에 즉시 노출됩니다.

외부 HTTP MCP 도구는 코드 수정 없이 `.env` 의 `EXTERNAL_MCP_TOOLS` 로 추가할 수 있습니다. 이 경우 서버 재시작 후 UI 에 노출됩니다.

---

## 9. API 명세 Quick Reference

### 에이전트 생성 예시

```bash
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "HR 연차 도우미",
    "version": "1.0.0",
    "purpose": "연차 관련 질문에 답변합니다.",
    "status": "DRAFT",
    "visibility": "DEPARTMENT",
    "agent_card": {"system_prompt": "당신은 HR 도우미입니다."},
    "tools": ["lookup_employee_leave", "search_knowledge_base"],
    "metadata": {"category": "HR"},
    "subscription_rule": {
      "watch_domains": ["hr"],
      "watch_tags": ["leave", "policy"],
      "min_priority": "medium",
      "is_active": true,
      "watch_intents": [],
      "watch_senders": [],
      "watch_roles": [],
      "ignore_senders": [],
      "ignore_tags": []
    }
  }'
```

### 에이전트 실행 예시

```bash
curl -X POST http://localhost:8000/api/v1/agents/<agent_id>/invoke \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"message": "E001 사번의 연차 잔여일을 알려줘"}'
```

### 응답 예시 (`invoke`)

```json
{
  "agent_id": "6f7aad5e-...",
  "agent_name": "HR 연차 도우미",
  "model_used": "openai/gpt-5",
  "input": "E001 사번의 연차 잔여일을 알려줘",
  "output": "김하늘 님의 남은 연차는 11일이며, 사용한 연차는 4일입니다.",
  "tool_calls": [
    {"name": "lookup_employee_leave", "args": {"employee_id": "E001"}}
  ],
  "steps": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "E001 사번의 연차 잔여일을 알려줘"},
    {"role": "assistant", "content": "{\"action\":\"tool\",\"tool\":\"lookup_employee_leave\",\"arguments\":{\"employee_id\":\"E001\"}}"},
    {"role": "tool", "name": "lookup_employee_leave", "content": "김하늘 님의 남은 연차는 11일..."},
    {"role": "assistant", "content": "{\"action\":\"final\",\"answer\":\"김하늘 님의 남은 연차는 11일이며...\"}"}
  ],
  "error": null
}
```

---

## 10. 알려진 한계 및 확장 포인트

| 항목 | 현재 상태 | 확장 방향 |
|------|-----------|-----------|
| **LLM 백엔드** | RunYour AI (`openai/gpt-5`) 고정 | `DEFAULT_LLM_MODEL` 변경 또는 표준 OpenAI API 전환 |
| **도구(MCP)** | 5종 내장, 모두 Mock 데이터 | 실제 DB/외부 API 연동 도구 추가 (섹션 8 참고) |
| **도구 실행** | 동기(sync) `tool.invoke()` | 비동기 지원 필요 시 `asyncio.to_thread()` 래핑 |
| **대화 컨텍스트** | 단일 요청 내에서만 유지 | `messages` 를 DB 에 저장해 멀티턴 대화 지원 |
| **구독 규칙 실행** | 저장만 됨, 실제 이벤트 라우팅 미구현 | `PH3-mesh-001` 메시지 브로커와 연동 필요 |
| **에이전트 권한** | 소유자만 편집/실행 가능 | `collaborators` 필드 기반 공동 소유 지원 |
| **max_tokens** | `max_completion_tokens=1200` 하드코딩 | `InvokeRequest` 에 옵션 필드로 노출 |
| **에러 처리** | `error` 필드에 문자열로 반환 | HTTP 상태 코드 세분화, 재시도 로직 추가 |

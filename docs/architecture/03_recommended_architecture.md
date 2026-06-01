# MeshBoard 추천 통합 아키텍처

> Grid-Agent의 **안전성/검증 파이프라인**과 MACRO-LLM의 **분산 협상/부분 관측**을
> MeshBoard 코드베이스(FastAPI + LangGraph agent_runtime + CityLearn Board)에
> 어떻게 결합할지를 정리한다.

## 1. 최상위 아키텍처

```text
┌─────────────────────────────────────────────────────────────────────┐
│                  React Workspace Board (WorkspacePage)              │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────────┐ │
│  │ Topology │ │ Messaging    │ │ Grid-Agent     │ │ Negotiation  │ │
│  │ Map      │ │ View         │ │ Validation     │ │ Trace        │ │
│  │ (Flow)   │ │              │ │ Panel          │ │ Inspector    │ │
│  └──────────┘ └──────────────┘ └────────────────┘ └──────────────┘ │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST + (later) SSE
┌───────────────────────────────▼─────────────────────────────────────┐
│                       FastAPI Backend                                │
│                                                                      │
│  api/v1/citylearn.py                                                 │
│   ├─ GET  /citylearn/board                                           │
│   ├─ POST /citylearn/grid-agent/analyze                              │
│   ├─ POST /citylearn/grid-agent/plan                                 │
│   └─ POST /citylearn/macro-mesh/negotiate                            │
│                                                                      │
│  services/                                                           │
│   ├─ citylearn_board.py            (snapshot, deterministic preview) │
│   ├─ citylearn_grid_agent.py                                         │
│   │    ├─ TopologyAnalyzer                                           │
│   │    ├─ ViolationDetector                                          │
│   │    ├─ HeuristicPlanner    (Phase 1)                              │
│   │    ├─ SandboxExecutor                                            │
│   │    ├─ ConstraintValidator                                        │
│   │    └─ OperatorSummarizer                                         │
│   ├─ citylearn_macro_mesh.py                                         │
│   │    ├─ CoProposerClient    (per building agent)                   │
│   │    ├─ MeanFieldAggregator                                        │
│   │    ├─ ConflictDetector                                           │
│   │    ├─ Negotiator          (Coordinator agent driver)             │
│   │    └─ Introspector        (semantic gradient updater)            │
│   ├─ agent_runtime.py         (LangGraph LLM loop, unchanged shape)  │
│   ├─ tool_catalog.py          (+ CityLearn validation tools)         │
│   └─ message_broker.py        (proposal/feedback A2A 발행)            │
│                                                                      │
│  schemas/                                                            │
│   ├─ citylearn_grid_agent.py  (Violation / Action / Plan / Result)   │
│   └─ citylearn_macro_mesh.py  (Proposal / MeanField / Conflict)      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  PostgreSQL                                                          │
│   ├─ workspaces.metadata_.agent_building_mapping (topology source)   │
│   ├─ citylearn_grid_agent_runs    (실험 로그)                        │
│   ├─ citylearn_grid_agent_actions (실험 로그)                        │
│   ├─ citylearn_macro_proposals    (round별 proposal)                 │
│   ├─ citylearn_macro_negotiations (round 결과 + mean_field)          │
│   └─ agent_strategy_versions      (semantic gradient versions)       │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. 통합 워크플로우 (한 step 처리)

```text
[T+k step trigger]
   │
   ▼
1) TopologyAnalyzer
     - get_board_snapshot(step, baseline_model, agent_mesh_mode)
     - workspace.metadata_.agent_building_mapping 결합
     - controllable_assets 목록 생성

2) ViolationDetector
     - peak / ramping / soc / mapping / fairness violation 탐지

   ┌─────────────────── MACRO-LLM 분산 협상 진입 ────────────────────┐
   │
3) Building Battery Agent들 (CoProposer, Round 1)
     - 각자 자기 building 상태 + mean_field summary 조회
     - agent_runtime.invoke()로 proposal JSON 발행
     - proposal은 message_broker로 Coordinator에게 publish

4) MeanFieldAggregator + ConflictDetector
     - 들어온 proposal들로 mean_field 갱신
     - 충돌(over_discharge / soc_risk / fairness 등) 산출

5) City Grid Coordinator (Negotiator, Round 2)
     - mean_field + conflicts + forbidden_action_keys를 building agent에게 broadcast
     - building agent들이 revised proposal 제출

   └─────────────────── 협상 종료 (max_rounds 도달) ─────────────────┘
   │
   ▼
6) HeuristicPlanner.merge_proposals() 또는 LLM Planner.final_plan()
     - 최종 district-level CityLearnPlan 생성

7) SandboxExecutor (k step rollout)
     - deepcopy(topology) 후 actions 적용
     - 변경된 score, soc, net_load 계산

8) ConstraintValidator
     - score_before/score_after, new_violations, clipped_actions 계산
     - approved=true/false 판정

9-A) approved=true
     - OperatorSummarizer가 한국어 운영자 요약 생성
     - 실험 로그 저장 (runs / actions / negotiations)
     - Board UI: 승인 badge + score delta + proposed actions overlay

9-B) approved=false
     - forbidden_action_keys 누적
     - max_iterations 미달이면 step 6으로 재계획
     - max_iterations 초과 시 rejected response 반환
     - Board UI: rejected badge + 사유 + remaining_violations

10) Introspector (선택적)
     - 최근 N step score 추이 악화 시에만 호출
     - 빌딩별 / Coordinator 별 semantic gradient 업데이트
     - agent_strategy_versions에 versioning
```

## 3. 모듈 책임 분리

| 모듈 | LLM 사용 여부 | 책임 | 절대 하지 말 것 |
| --- | --- | --- | --- |
| TopologyAnalyzer | ❌ | snapshot + mapping 결합, controllable_assets 산출 | LLM 호출 |
| ViolationDetector | ❌ | 수치 비교로 violation 탐지 | 자연어 추론 |
| CoProposerClient | ✅ (per building agent) | 자기 building 후보 action 생성 | 자기 외 building action 직접 수정 |
| MeanFieldAggregator | ❌ | 평균/분산 계산 | LLM 호출 |
| ConflictDetector | ❌ | 규칙 기반 충돌 탐지 | 자연어 추론 |
| Negotiator | ✅ (Coordinator agent) | mean_field + conflict 기반 재제안 요청 | 직접 action 적용 |
| HeuristicPlanner | ❌ | proposal 병합 fallback | LLM 호출 |
| SandboxExecutor | ❌ | deepcopy 후 action 적용, 새 state 반환 | 원본 snapshot 변경 |
| ConstraintValidator | ❌ | score 계산, violation 재탐지, approved 결정 | LLM 호출 |
| OperatorSummarizer | ⚠️ Phase 2부터 LLM | 운영자용 한국어 요약 | 추가 action 제안 |
| Introspector | ✅ | semantic gradient 자연어 규칙 작성 | action 직접 수정 |

## 4. 데이터 모델 추가 (Pydantic + DB)

### 4.1 Pydantic 스키마 파일

- `backend/app/schemas/citylearn_grid_agent.py`
  - `CityLearnViolation`, `CityLearnAction`, `CityLearnPlan`, `CityLearnValidationResult`
  - `GridAgentAnalyzeRequest/Response`, `GridAgentPlanRequest/Response`
- `backend/app/schemas/citylearn_macro_mesh.py`
  - `BuildingProposal`, `MeanFieldSummary`, `ConflictReport`, `NegotiationFeedback`
  - `MacroMeshNegotiateRequest/Response`

### 4.2 DB 테이블 (Phase 4부터)

| 테이블 | PK | 핵심 컬럼 | 용도 |
| --- | --- | --- | --- |
| `citylearn_grid_agent_runs` | `run_id` | workspace_id, step, baseline_model, approved, score_before, score_after, payload(JSONB), created_at | run 단위 trace |
| `citylearn_grid_agent_actions` | `action_id` | run_id, building_id, action_value, mode, reason, confidence | building별 action |
| `citylearn_macro_proposals` | `proposal_id` | run_id, round_index, building_id, payload(JSONB) | round별 proposal |
| `citylearn_macro_negotiations` | `nego_id` | run_id, round_index, mean_field(JSONB), conflicts(JSONB) | round 결과 |
| `agent_strategy_versions` | `version_id` | agent_id, version, semantic_gradient, parent_version_id, created_at | introspection 버전링 |

모든 테이블에 `workspace_id` index를 둔다. payload JSONB는 sanitize 후 저장 (secret 제외).

## 5. API 엔드포인트

```text
GET  /api/v1/citylearn/board                       (기존)
POST /api/v1/citylearn/grid-agent/analyze          topology + violation 만 반환
POST /api/v1/citylearn/grid-agent/plan             heuristic/LLM plan + sandbox 검증
POST /api/v1/citylearn/macro-mesh/negotiate        round 기반 협상 실행
POST /api/v1/citylearn/grid-agent/commit-preview   UI trace 저장 (live 적용 없음)
GET  /api/v1/citylearn/grid-agent/runs             과거 run 목록
GET  /api/v1/citylearn/grid-agent/runs/{run_id}    상세 trace
GET  /api/v1/citylearn/kpi                         KPI 집계 (실험 리포트용)
```

원칙:
- **`commit-preview` 외에는 모두 비파괴(preview-only)**.
- workspace 권한 검증을 모든 endpoint에서 수행.
- error response는 `validation_failed` / `runtime_failed` / `forbidden` 등을 명확히 구분.

## 6. LangGraph 노드 확장

기존 `agent_runtime.py`의 `agent_node ↔ mcp_tool_node` 그래프는 **변경하지 않는다**.
대신 Grid-Agent orchestration이 외부에서 `agent_runtime`을 invoke한다.

선택적으로 별도 LangGraph workflow를 추가할 수 있다:

```text
START
  ↓
topology_node       (TopologyAnalyzer)
  ↓
violation_node      (ViolationDetector)
  ↓
coproposer_node     (per building agent invoke, parallel)
  ↓
aggregator_node     (MeanFieldAggregator + ConflictDetector)
  ↓
negotiator_node     (Coordinator invoke, max_rounds 제한)
  ↓
sandbox_node        (SandboxExecutor)
  ↓
validator_node      (ConstraintValidator)
  ↓
[approved?]
  ├─ true → summarizer_node → END
  └─ false (iteration < max) → coproposer_node (feedback 주입)
  └─ false (iteration ≥ max) → rejected_summary_node → END
```

이 별도 워크플로우는 Phase 3 이후 도입. Phase 1~2까지는 순차 함수 호출로 구현해 디버깅을 단순화한다.

## 7. Seed Agents

`seed_agents.py` (또는 `seed_grid_agents.py`)에 다음 3종 등록:

1. **City Grid Coordinator** (district level)
   - tools: `get_citylearn_board_state`, `detect_citylearn_violations`, `validate_citylearn_battery_plan`
   - role: Negotiator + Planner
   - system_prompt 핵심: "당신은 district coordinator입니다. action 적용 전 반드시 validate를 호출하고, mean-field summary로 빌딩들을 비교하십시오."

2. **Building Battery Agent** (per building, quantity=17로 할당)
   - tools: `get_citylearn_board_state` (자기 building만 필터)
   - role: CoProposer
   - system_prompt 핵심: "당신은 하나의 building agent입니다. 할당된 building_id 외 자산을 제어하지 마십시오. SOC 0.2 미만 discharge 금지, 0.9 초과 charge 금지."

3. **CityLearn Constraint Guard** (validator)
   - tools: `validate_citylearn_battery_plan`
   - role: 외부 검증 인격
   - system_prompt 핵심: "검증되지 않은 plan을 승인하지 마십시오. score_after < score_before이고 새 SOC/invalid violation이 없을 때만 approve."

워크스페이스에 위 3종을 배치하면 토폴로지 맵에 다음이 보인다:
- Coordinator 1 ↔ Constraint Guard 1 ↔ Building Battery Agent × 17 (Coordinator 경유)

## 8. Frontend 통합 지점

`frontend/src/pages/WorkspacePage.tsx`에 추가:

1. **Grid-Agent Validation Panel** (Board 우측 inspector)
   - Run Grid-Agent Plan 버튼
   - approved/rejected badge
   - score_before → score_after metric
   - initial_violations 목록
   - proposed actions 목록
   - operator_summary 표시
   - iteration trace toggle

2. **Negotiation Trace Inspector** (Map 모드 우측)
   - Round별 proposal 목록
   - mean_field summary 카드
   - conflicts 목록
   - forbidden_action_keys 누적 목록

3. **Building Heatmap Action Overlay**
   - 빌딩 카드에 proposed action 값
   - charge/discharge/hold 시각 구분
   - confidence를 opacity로 표현
   - validation rejected 시 붉은 outline

4. **Strategy Version Inspector** (선택)
   - 각 agent별 semantic_gradient 버전 timeline
   - 운영자가 승인/disable 가능

`frontend/src/api/citylearn.ts`에는 `CityLearnGridAgentPlanResponse`, `CityLearnNegotiationResponse` 등 타입과 client 함수만 추가한다 (기존 board API는 건드리지 않는다).

## 9. Phased 구현 로드맵

### Phase 1 — Grid-Agent Deterministic MVP (LLM 없음)
- schemas/citylearn_grid_agent.py
- services/citylearn_grid_agent.py (Topology, Violation, Heuristic, Sandbox, Validator, Summarizer)
- api/v1/citylearn.py에 analyze, plan 추가
- Board UI Validation Panel

### Phase 2 — LLM Planner 연결
- tool_catalog에 검증 도구 추가
- City Grid Coordinator, Constraint Guard seed
- agent_runtime invoke를 Grid-Agent orchestration에 연결
- forbidden_action_keys 누적 + max_iterations replanning

### Phase 3 — MACRO-LLM 분산 협상
- schemas/citylearn_macro_mesh.py
- services/citylearn_macro_mesh.py (CoProposer, MeanField, Conflict, Negotiator)
- Building Battery Agent seed × 17
- api/v1/citylearn.py에 macro-mesh/negotiate 추가
- Board UI Negotiation Trace Inspector + Heatmap overlay

### Phase 4 — 실험 로그 + KPI
- DB migration: runs/actions/proposals/negotiations/strategy_versions
- KPI 집계 service + endpoint
- Board UI에 baseline vs grid-agent vs macro-mesh KPI 비교

### Phase 5 — Introspection + Live CityLearn env
- Introspector service
- agent_strategy_versions 저장 + rollback
- citylearn env step bridge (deterministic preview → live env)
- Ablation 실험 자동화

## 10. 운영 안정성 / 비용 / 안전

| 항목 | 결정 |
| --- | --- |
| LLM 호출 횟수 상한 | `MAX_TOOL_STEPS=6` (agent_runtime 기본) + `max_iterations=3` per run + `max_rounds=2` per negotiation |
| 단일 LLM call timeout | 30초 (RunYour AI proxy 한계 고려) |
| 큰 모델 / 작은 모델 분리 | Coordinator는 큰 모델, Building agent는 작은 모델 검토 (Phase 4) |
| Snapshot 캐싱 | `get_board_snapshot`은 이미 `@lru_cache`. step 단위 캐시 유지 |
| 민감 정보 sanitize | run payload JSONB 저장 전 secret/PII 필터 |
| Human approval | MVP 전 phase에서 자동 적용 없음. `commit-preview`까지만 |
| 실패 trace 보존 | 모든 rejected run도 저장. 분석/논문 데이터로 활용 |

## 11. 한 화면 요약

```text
Grid-Agent: 안전성을 보장하는 수직 파이프라인
   Topology → Violation → Plan → Sandbox → Validate → Summarize
                                        ↑ 실패 시 forbidden_action_keys로 재계획

MACRO-LLM: 부분 관측 빌딩 단위 수평 분산 협상
   Building agents (CoProposer)
        ↓ proposal
   Coordinator (Negotiator + mean_field + conflict)
        ↓ revised proposals
   동일한 Grid-Agent 파이프라인으로 fall through

Introspector: 운영 중 학습
   score 악화 시에만 호출 → semantic gradient → 다음 prompt 주입
```

다음 문서 [`04_experiment_plan.md`](./04_experiment_plan.md)는
이 아키텍처를 어떻게 측정/비교할지를 다룬다.
[`feature_list.json`](./feature_list.json)은 위 Phase 1~5를 추적 가능한
feature 단위로 분해한 것이다.

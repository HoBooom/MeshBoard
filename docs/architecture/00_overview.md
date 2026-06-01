# MeshBoard Agentic Architecture — Overview

> 본 디렉토리는 `docs/Grid_Agent.md`와 `docs/MACRO_LLM.md` 두 논문 분석을
> 현재 MeshBoard 코드베이스(FastAPI + LangGraph agent_runtime + CityLearn Board)
> 기준으로 재해석하고, 실제 적용 가능한 아키텍처/실험/feature 단위로
> 구조화한 문서 모음이다.

## 1. 문서 구성

| 파일 | 역할 |
| --- | --- |
| [`00_overview.md`](./00_overview.md) | 통합 비전, 두 논문의 차이/상호보완, 현재 시스템 매핑 (본 문서) |
| [`01_paper_grid_agent.md`](./01_paper_grid_agent.md) | Grid-Agent 논문 재요약 + MeshBoard 적용 포인트 |
| [`02_paper_macro_llm.md`](./02_paper_macro_llm.md) | MACRO-LLM 논문 재요약 + MeshBoard 적용 포인트 |
| [`03_recommended_architecture.md`](./03_recommended_architecture.md) | 두 논문을 결합한 MeshBoard 추천 아키텍처 |
| [`04_experiment_plan.md`](./04_experiment_plan.md) | Baseline 비교 / Ablation / KPI 실험 계획 |
| [`feature_list.json`](./feature_list.json) | 통합 구현 feature 추적 리스트 |

상세 논문 풀텍스트 분석은 기존 `docs/Grid_Agent.md`, `docs/MACRO_LLM.md`에 유지하고,
본 architecture 문서들은 **현재 MeshBoard 코드베이스에 직접 적용 가능한 결정사항**만 다룬다.

기존 `docs/mesh/grid_agent_overview.md`는 Grid-Agent 한정 단일 기준 문서로 유지되고,
본 디렉토리는 **두 논문 통합 + 실험 + feature 추적**을 다룬다는 점에서 역할이 분리된다.

## 2. 통합 비전

MeshBoard는 다음과 같은 두 축의 시스템이다.

1. **Agentic Mesh 플랫폼**: 워크스페이스에 여러 에이전트를 배치하고, 메시지/구독/토폴로지 맵으로 협업을 관찰한다.
2. **CityLearn Board**: 도시 에너지(17 빌딩, `electrical_storage` action, 8760 step) 환경에 대해 baseline vs Agent-Mesh의 효과를 시각화한다.

두 논문은 이 두 축을 각각 강화한다.

- **Grid-Agent**: 단일 도메인(전력망)에서 LLM이 안전하게 제어 전략을 만들고, 시뮬레이터로 검증하는 **"수직" 안정성** 축.
- **MACRO-LLM**: 여러 에이전트가 부분 관측 환경에서 제안/협상/자기반성으로 협업하는 **"수평" 분산 협업** 축.

MeshBoard에서는 이 둘이 별개가 아니라 **하나의 워크플로우에서 만나야 한다**.

```text
[Building Battery Agent #1..#17]  ← MACRO-LLM 식 분산 제안 + Negotiation
            ↓ (proposal)
[City Grid Coordinator]           ← MACRO-LLM Negotiator + Grid-Agent Planner
            ↓ (sandbox plan)
[CityLearn Constraint Guard]      ← Grid-Agent Validator
            ↓ (approved actions)
[Operator + Board UI]             ← Grid-Agent Summarizer + Human-in-the-loop
```

즉, 빌딩 단위에서는 MACRO-LLM 식 **국소 관측 기반 협상**으로 후보 action을 만들고,
district 단위에서는 Grid-Agent 식 **sandbox 검증 + rollback**으로 안전성을 보장한다.

## 3. 두 논문의 차이와 상호보완

| 축 | Grid-Agent | MACRO-LLM |
| --- | --- | --- |
| 문제 정의 | 전력망 위반(voltage/thermal/disconnected) 해결 | 시공간적 부분 관측 환경에서 분산 협업 |
| 아키텍처 | 5-에이전트 파이프라인 (Topology→Planner→Executor→Validator→Summarizer) | 각 에이전트 안에 3 모듈 (CoProposer/Negotiator/Introspector) |
| 통신 | 중앙 Planner가 모든 정보 통합 | Peer-to-peer + mean-field summary 교환 |
| 검증 | Power flow solver + sandbox + rollback | Rollout simulation + multi-round negotiation |
| 학습 | 성공 trace 축적 (RAG/fine-tune 후보) | Semantic gradient descent (자연어 전략 업데이트) |
| 약점 | 단일 도메인, 중앙 의존성 | 안전성 검증이 약함, 비용 폭발 위험 |
| 강점 | 안전성 + 설명 가능성 | 확장성 + 부분 관측 환경에 강건 |

**핵심 합의**: 두 논문 모두 **LLM은 제어기가 아니라 후보 생성기**이며,
실제 적용은 **structured JSON + 외부 검증**이 담당한다는 점이 일치한다.

## 4. 현재 MeshBoard 코드베이스 매핑

| 논문 개념 | 현재 코드 | 상태 |
| --- | --- | --- |
| Agent Registry | `backend/app/models/agent.py`, `backend/app/api/v1/agents.py` | ✅ 존재 |
| LangGraph runtime | `backend/app/services/agent_runtime.py` (agent_node ↔ mcp_tool_node) | ✅ 존재 |
| MCP Tool Catalog | `backend/app/services/tool_catalog.py` | ✅ 존재 (5종 도구) |
| Topology graph | `backend/app/models/workspace.py` (WorkspaceNode, WorkspaceEdge) | ✅ 존재 |
| Mesh A2A 메시지 | `backend/app/services/message_broker.py`, `messages.py` | ✅ 존재 |
| CityLearn snapshot | `backend/app/services/citylearn_board.py` | ✅ 존재 |
| SACRBC baseline | `backend/app/services/citylearn_sacrbc_inference.py` | ✅ 존재 |
| Workspace metadata mapping | `workspace.metadata_.agent_building_mapping` | ✅ 사용 중 |
| Grid-Agent 엔진 (Topology/Violation/Sandbox/Validator) | (없음) | ❌ 신규 |
| MACRO-LLM 모듈 (CoProposer/Negotiator/Introspector) | (없음) | ❌ 신규 |
| 실험 로그 테이블 | (없음) | ❌ 신규 |
| Board UI Grid-Agent 패널 | `frontend/src/pages/WorkspacePage.tsx` 일부 hook 있음 | ⚠️ 부분 |

## 5. 적용 원칙 (두 논문 공통)

1. **LLM은 후보 생성기, 실제 적용은 deterministic validator가 결정한다.**
2. **모든 action은 sandbox state에서 먼저 평가하고, 원본 snapshot을 변경하지 않는다.**
3. **CityLearn `phase_all`에서는 `electrical_storage` action만 허용한다. (-1.0 ~ 1.0)**
4. **메시지/proposal은 자연어가 아닌 JSON schema로 강제한다.**
5. **검증 실패 시 같은 action sequence를 반복하지 않도록 forbidden_action_keys를 누적한다.**
6. **이웃 정보 공유는 raw state가 아닌 mean-field summary 우선으로 사용한다.**
7. **Negotiation/replanning은 `max_rounds`와 `timeout`으로 제한한다.**
8. **Human approval을 기본값으로 두고, 자동 적용은 별도 phase에서만 활성화한다.**
9. **실패 trace도 저장한다. 실패는 재계획 품질을 높이는 데이터다.**

## 6. 의사결정 사항

- **MVP action space**: `electrical_storage` 하나만 사용. EV/HVAC는 phase_all에서 비활성.
- **MVP topology source**: `workspace.metadata_.agent_building_mapping`을 single source of truth로 사용.
- **MVP planner**: 먼저 deterministic heuristic으로 워크플로우를 완성한 뒤 LLM Planner로 교체. LLM 실패 원인을 검증 로직과 분리하기 위함.
- **MVP negotiation depth**: 2 round (round 1: 제안, round 2: mean-field 반영 재제안).
- **MVP introspection scope**: 직전 N=5 step의 성공/실패 trace만 prompt에 주입.
- **Live CityLearn env step 연동은 후순위**: deterministic preview 기반 Grid-Agent + Board UI가 안정화된 뒤 연결.

## 7. 구현 우선순위

```text
Phase 1: Grid-Agent Deterministic MVP
   - schemas + TopologyAnalyzer + ViolationDetector + HeuristicPlanner
   - SandboxExecutor + ConstraintValidator + OperatorSummarizer
   - /grid-agent/analyze, /grid-agent/plan API
   - Board UI Validation Panel

Phase 2: LLM Planner 연결
   - tool_catalog에 validate_citylearn_battery_plan 등 추가
   - Seed agents: City Grid Coordinator, Constraint Guard
   - agent_runtime을 Grid-Agent orchestration에서 호출
   - Replanning loop + forbidden_action_keys

Phase 3: MACRO-LLM 분산 협상 추가
   - Building Battery Agent들이 local proposal 발행
   - Coordinator가 mean-field summary + conflict detection
   - 2-round negotiation
   - Building heatmap에 per-building proposal overlay

Phase 4: Introspection + 실험 로그
   - 성공/실패 trace 저장 테이블
   - Semantic gradient (자연어 전략) 저장
   - KPI dashboard (approval rate, action efficiency, fairness)

Phase 5: Live CityLearn env step + Ablation 실험
   - CityLearn env 연동
   - Baseline (BasicRBC/SACRBC/MARLISA) vs Grid-Agent vs MACRO-Mesh 비교
   - 모듈 제거 ablation
```

상세는 [`03_recommended_architecture.md`](./03_recommended_architecture.md)와
[`04_experiment_plan.md`](./04_experiment_plan.md)에 있다.

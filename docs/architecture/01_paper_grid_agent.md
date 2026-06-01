# Grid-Agent 논문 적용 분석

> 본 문서는 `docs/Grid_Agent.md`의 상세 논문 분석을 MeshBoard 코드베이스에
> 직접 적용 가능한 단위로 압축한 것이다. 풀텍스트 해설은 원본 문서를 참조한다.

## 1. 논문 핵심 (3줄 요약)

1. 전력망 위반(voltage / thermal / disconnected)을 LLM이 직접 풀지 않고, **LLM은 전략을 만들고 시뮬레이터가 검증**하는 분리 구조.
2. 5개의 역할 분리 에이전트: Topology → Planner → Executor → Validator → Summarizer. 실패 시 Validator → Planner 피드백 루프.
3. `sandbox copy → apply actions → power flow → validate → approve or rollback`이 안전성을 보장하는 핵심 메커니즘.

## 2. MeshBoard 도메인 치환

| Grid-Agent 개념 | MeshBoard CityLearn 적용 |
| --- | --- |
| Bus / Line / Transformer | Building (17개) / pricing / carbon / weather |
| Voltage violation | SOC 하한/상한 위험 |
| Thermal overload | district net load peak / ramping 초과 |
| Disconnected bus | 빌딩에 agent 미할당 (mapping violation) |
| Power flow solver | CityLearn env step (후순위) 또는 `citylearn_board.py` deterministic preview |
| Switch operation / Battery dispatch / Load curtailment | `electrical_storage` action ∈ [-1.0, 1.0] (음수=방전, 양수=충전) |
| disruptive action 최소화 | 특정 빌딩에 부담 집중 방지 (fairness) |

CityLearn `phase_all`에서는 active action이 `electrical_storage` 하나라 MVP action space는 배터리 충방전 뿐이다.

## 3. 5 에이전트 → MeshBoard 매핑

| 논문 에이전트 | MeshBoard 구현 | 구현 방식 |
| --- | --- | --- |
| **TopologyAgent** | `backend/app/services/citylearn_grid_agent.py::TopologyAnalyzer` | Pure Python. `get_board_snapshot()` 결과와 `workspace.metadata_.agent_building_mapping` 결합 |
| **PlannerAgent** | `HeuristicPlanner` (Phase 1) → LLM Planner via `agent_runtime` (Phase 2) | Phase 1: SOC + net load 기반 결정적 규칙. Phase 2: agent_runtime의 JSON 프로토콜 사용 |
| **ExecutorAgent** | `SandboxExecutor` | `copy.deepcopy(snapshot)`에 action 적용. 절대 원본 변경 금지 |
| **ValidatorAgent** | `ConstraintValidator` | Pure Python. `score_before`/`score_after` 비교 + 새 violation 탐지 |
| **SummarizerAgent** | `OperatorSummarizer` (Phase 1) → LLM Summarizer (Phase 2) | Phase 1: template 기반 한국어 요약. Phase 2: LLM 요약 |

**중요**: Topology/Executor/Validator는 LLM이 아니라 deterministic Python으로 구현한다.
LLM에게 숫자 계산이나 sandbox 실행을 맡기지 않는다.

## 4. Violation 모델 (MeshBoard 버전)

```python
ViolationType = Literal[
    "peak",            # district net load가 threshold 초과
    "ramping",         # 직전 step 대비 load 급변
    "soc",             # SOC < 0.20 or SOC > 0.90
    "mapping",         # 빌딩에 agent 미할당
    "fairness",        # 특정 빌딩 부담 집중 (직전 N step action 누적)
    "invalid_action",  # 범위 초과, 존재하지 않는 building_id
]
```

각 violation에는 `severity ∈ [0, 1]`, `current_value`, `limit_value`, `description`을 부여한다.

## 5. Action / Plan / Validation JSON 스키마

`backend/app/schemas/citylearn_grid_agent.py`로 추가 예정.

```python
class CityLearnAction(BaseModel):
    building_id: str            # 존재하는 빌딩만 허용
    action: float               # Field(ge=-1.0, le=1.0)
    mode: Literal["charge", "discharge", "hold"]
    reason: str
    expected_effect: str
    confidence: float           # Field(ge=0.0, le=1.0)

class CityLearnPlan(BaseModel):
    strategy_summary: str
    actions: list[CityLearnAction]
    risk_assessment: str

class CityLearnValidationResult(BaseModel):
    approved: bool
    score_before: float
    score_after: float
    resolved_violations: list[CityLearnViolation]
    remaining_violations: list[CityLearnViolation]
    new_violations: list[CityLearnViolation]
    clipped_actions: list[CityLearnAction]
    feedback: str
```

## 6. Sandbox + Rollback 메커니즘

```python
# 의사 코드
def run_plan(snapshot, mapping, planner) -> ValidationResult:
    topology = TopologyAnalyzer().analyze(snapshot, mapping)
    before_violations = ViolationDetector().detect(topology)

    for iteration in range(max_iterations):
        plan = planner.propose(topology, feedback=last_feedback)
        sandbox = SandboxExecutor().execute(topology, plan.actions)
        result = ConstraintValidator().validate(topology, sandbox, plan.actions)
        if result.approved:
            return result
        last_feedback = build_feedback(result)   # forbidden_action_keys 누적
    return result  # 최종 rejected
```

핵심 규칙:
- `iteration`은 plan 단위 rollback (단일 action 단위 rollback은 MVP 범위 밖).
- `forbidden_action_keys = [f"{building_id}:{action}"]`를 다음 prompt에 누적해 동일 plan 반복을 막는다.
- `max_iterations` 초과 시 `approved=false` + feedback을 그대로 반환하여 UI가 표시한다.

## 7. Scoring 공식 (deterministic baseline)

```text
district_load        = sum(building.agent_mesh_net_load_kwh)
soc_penalty          = sum(10 for b if b.battery_soc < 0.15 or b.battery_soc > 0.95)
peak_penalty         = max(0, district_load - peak_threshold) * 2.0
ramping_penalty      = max(0, |district_load_t - district_load_{t-1}| - ramp_threshold) * 1.5
fairness_penalty     = stddev(|action[b]| for b in buildings) * 1.0

score = district_load + soc_penalty + peak_penalty + ramping_penalty + fairness_penalty
```

threshold 값 (`peak_threshold=55.0`, `ramp_threshold=20.0`, SOC bounds 등)은 **상수 파일**로 분리한다 (예: `backend/app/services/citylearn_grid_agent_constants.py`). magic number를 코드 본문에 박지 않는다.

## 8. Tool Catalog 확장 (LLM Planner 연결용)

`backend/app/services/tool_catalog.py`에 다음 도구를 추가한다.

| Tool ID | 결정성 | 역할 |
| --- | --- | --- |
| `get_citylearn_board_state` | deterministic | 현재 step snapshot을 축약 JSON으로 반환 |
| `detect_citylearn_violations` | deterministic | peak/ramping/SOC/mapping/fairness violation 반환 |
| `validate_citylearn_battery_plan` | deterministic | action list sandbox 검증, JSON 응답 |

핵심 원칙:
- `actions_json` 파라미터는 **문자열 JSON**으로 받는다 (RunYour AI 프록시의 function-calling 호환성 이슈 회피, 기존 `agent_runtime.py`와 일관).
- 도구 출력은 `approved`, `score_before`, `score_after`, `feedback`, `remaining_violations`만 포함. snapshot 전체를 반복해 반환하지 않는다 (토큰 비용).

## 9. Planner Prompt 핵심

LLM Planner의 system prompt에는 다음을 명시한다.

```text
- action 범위는 [-1.0, 1.0]
- 음수 = discharge (net load 감소), 양수 = charge (net load 증가)
- SOC < 0.20인 building에는 discharge 금지
- SOC > 0.90인 building에는 charge 금지
- 존재하지 않는 building_id 사용 금지
- EV/HVAC/washing machine은 phase_all에서 비활성, 제안 금지
- load curtailment는 MVP action space에 없음
- 검증 실패 plan은 forbidden_action_keys에 등록되므로 그대로 반복 금지
- 답변은 반드시 agent_runtime JSON 프로토콜:
    {"action":"tool","tool":"validate_citylearn_battery_plan", "arguments":{...}}
    또는
    {"action":"final","answer":"..."}
```

`agent_runtime.py`는 이미 이 JSON 프로토콜을 강제하고 있으므로 (`AGENT_INVALID_RESPONSE_MESSAGE` fallback 포함), 별도 텍스트 파싱 레이어를 만들지 않는다.

## 10. Workspace metadata 활용

`workspace.metadata_.agent_building_mapping`이 topology의 single source of truth다.

예상 구조:

```json
{
  "environment_template_id": "citylearn-2022",
  "central_controller_agents": [
    { "agent_id": "<uuid>", "agent_name": "City Grid Coordinator" }
  ],
  "buildings": [
    {
      "building_id": "Building_1",
      "assigned_agent_id": "<uuid>",
      "assigned_agent_name": "Building Battery Agent",
      "metadata": { "battery_capacity": 6.4, "pv_nominal_power": 5.0 }
    }
  ]
}
```

- `central_controller_agents`가 비어 있으면 Board는 `demo_heuristic` 모드를 권장.
- `assigned_agent_id`가 없는 building → `mapping` violation 생성.
- 미할당 building에도 fallback heuristic action을 낼 수는 있으나, 그 action의 `confidence`는 낮게 표시한다.

## 11. 적용 시 주의점

| 항목 | 결정 |
| --- | --- |
| LLM이 sandbox 실행 / 숫자 계산 | ❌ 금지. Python validator만 |
| 자연어 action 출력 | ❌ 금지. JSON schema 강제 |
| 검증 없이 commit | ❌ 금지. preview-only API부터 시작 |
| 큰 snapshot을 매 prompt에 통째로 주입 | ❌ violation-centric 요약으로 축소 |
| 성공 여부만 평가 | ❌ action efficiency / new_violation_rate / fairness 함께 측정 |
| 자동 적용 | ❌ MVP는 Human approval 기본. 자동 적용은 별도 phase |

## 12. 본 논문에서 가져올 핵심

1. **LLM 분리 원칙**: 전략 생성과 검증을 분리.
2. **Sandbox + Rollback**: 모든 action은 복사본에서 먼저 평가.
3. **Iterative replanning**: 실패 feedback → 재계획 (단, max_iterations 제한).
4. **Action efficiency 지표**: 단순 success rate가 아닌 "action 수 대비 개선량" 측정.
5. **Operator-facing Summary**: Audit-friendly Korean 요약을 항상 생성.

다음 문서 [`02_paper_macro_llm.md`](./02_paper_macro_llm.md)는 이 위에 **분산 협업 / 부분 관측 / 협상**을 어떻게 얹을지를 다룬다.

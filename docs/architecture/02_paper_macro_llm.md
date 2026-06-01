# MACRO-LLM 논문 적용 분석

> 본 문서는 `docs/MACRO_LLM.md`의 상세 논문 분석을 MeshBoard에 적용 가능한
> 단위로 압축한 것이다. 풀텍스트 해설은 원본 문서를 참조한다.

## 1. 논문 핵심 (3줄 요약)

1. 현실 시스템은 **시공간적 부분 관측성**을 가진다. 즉, 각 에이전트는 자기 주변 일부만 보고, 미래도 일부만 안다.
2. 각 에이전트 안에 **CoProposer + Negotiator + Introspector**의 3 모듈을 두어 제안 → 협상 → 자기반성을 반복한다.
3. 모든 상태를 공유하지 않고 **mean-field summary**로 통신량을 일정 수준으로 유지하며, **semantic gradient descent**(자연어 피드백)로 전략을 업데이트한다.

## 2. MeshBoard 도메인 치환

| MACRO-LLM 개념 | MeshBoard CityLearn 적용 |
| --- | --- |
| Spatial partial observability | 빌딩 agent는 자기 building과 이웃 N개 평균만 본다 |
| Temporal partial observability | history window=K step (예: 24~72)만 본다 |
| Neighbor agent | 동일 district 내 다른 building agent + Coordinator |
| Mean-field summary | district 평균 net load, 평균 SOC, 평균 PV, peak/ramp 지표 |
| Proposal | 빌딩별 `electrical_storage` action 후보 |
| Negotiation conflict | 동시 discharge 과다 / SOC 위반 / fairness 위반 |
| Rollout simulation | `SandboxExecutor` 1~3 step preview (k=1~3) |
| Semantic gradient | 운영자/Coordinator가 남기는 "다음에는 이렇게 해라" 자연어 규칙 |

CityLearn은 본래 중앙 dispatch도 가능하지만, MeshBoard에서는 의도적으로 빌딩 단위 분산 관측 모델을 채택해 MACRO-LLM 구조를 구현한다.

## 3. 3 모듈 → MeshBoard 매핑

### 3.1 CoProposer

빌딩 agent가 자기 상태 + 이웃 mean-field summary를 보고 **자기 action**과 **이웃 행동 제안**을 함께 낸다.

```json
{
  "agent_id": "Building_3",
  "self_action": { "type": "discharge", "value": -0.3 },
  "neighbor_suggestions": {
    "Building_4": { "hint": "charge_if_pv_available" },
    "Building_7": { "hint": "hold_to_preserve_soc" }
  },
  "reason": "현재 district peak 진입 직전이며 내 SOC 0.72, 이웃 평균 SOC 0.41",
  "expected_effect": "district peak 1.4kWh 감소",
  "confidence": 0.78
}
```

구현 위치: `backend/app/services/citylearn_macro_mesh.py::CoProposer`.

핵심 규칙:
- LLM은 **후보 생성만** 담당. 실제 action은 `SandboxExecutor` + `ConstraintValidator` 통과 후에만 유효.
- rollout horizon `k=1~3` (MVP는 k=1). `SandboxExecutor`를 그대로 활용.
- 자기 building 외 자산은 **제안(hint)**만 가능, 직접 수정은 불가.

### 3.2 Negotiator

여러 빌딩의 proposal을 모아 충돌을 평가하고 mean-field summary로 묶어 재제안을 유도한다.

구현 위치: `City Grid Coordinator` agent + `Negotiator` service (`citylearn_macro_mesh.py::Negotiator`).

핵심 동작:

```python
class Negotiator:
    def aggregate_mean_field(proposals) -> dict:
        # avg_soc, avg_net_load, demand_variance, total_action_magnitude 등
        ...

    def detect_conflicts(proposals) -> list[Conflict]:
        # 동시 discharge 과다, SOC 임박 building에 discharge 요청, fairness 위반
        ...

    def assign_confidence(proposals, mean_field) -> list[ScoredProposal]:
        ...

    def request_revision(scored_proposals) -> list[RevisionFeedback]:
        # 빌딩 agent에게 mean_field와 conflict를 다시 보냄
        ...
```

**MVP negotiation depth = 2 round**:
- Round 1: 모든 빌딩이 독립적으로 proposal 발행
- Round 2: Coordinator가 mean-field summary + conflict feedback 배포, 빌딩들이 수정 proposal 발행
- Round 2 종료 시 합의 / Coordinator final pick / Constraint Guard 검증

`max_rounds = 2`, `timeout_seconds = 30`을 settings 상수로 고정한다.

### 3.3 Introspector

각 빌딩 agent와 Coordinator는 직전 N step의 reward/score 변화를 보고 **자연어 전략 규칙**을 업데이트한다.

저장 위치: 신규 테이블 `agent_strategy_versions` (또는 `agent.metadata_.strategy_versions[]`).

```json
{
  "agent_id": "<uuid>",
  "version": 4,
  "updated_at_step": 4210,
  "semantic_gradient": "지난 5 step 동안 SOC 0.25~0.3 구간에서도 discharge를 제안해 검증 실패가 3회 발생했다. 다음부터는 SOC < 0.35이면 discharge 제안을 보류한다.",
  "scope": "self_only | broadcasted"
}
```

MVP 규칙:
- reward(score)가 **악화된 경우에만** Introspector 호출. 비용 절감.
- 직전 N=5 trace만 prompt에 주입. 그 이상은 요약.
- 업데이트된 전략은 versioning. 이상하면 이전 버전으로 rollback 가능.
- `scope=self_only`가 기본. `broadcasted`는 Coordinator만 발행.

## 4. Proposal / Negotiation 메시지 스키마

`backend/app/schemas/citylearn_macro_mesh.py`로 추가 예정.

```python
class BuildingProposal(BaseModel):
    proposal_id: str
    sender_agent_id: str
    building_id: str
    time_step: int
    round_index: int            # 0=initial, 1=revised
    self_action: CityLearnAction
    neighbor_hints: dict[str, str]      # building_id → 한 줄 hint
    expected_effect: dict[str, float]   # peak_reduction_kwh, soc_risk 등
    confidence: float
    observation_window: int             # k step lookback
    rationale: str

class MeanFieldSummary(BaseModel):
    time_step: int
    avg_net_load_kwh: float
    var_net_load_kwh: float
    avg_battery_soc: float
    avg_pv_generation_kwh: float
    district_peak_threshold: float
    critical_building_ratio: float       # SOC bound 근접 building 비율
    weight_sum: float

class ConflictReport(BaseModel):
    conflict_id: str
    type: Literal["over_discharge", "soc_risk", "fairness", "resource_contention"]
    involved_agents: list[str]
    involved_buildings: list[str]
    severity: float
    description: str

class NegotiationFeedback(BaseModel):
    round_index: int
    mean_field: MeanFieldSummary
    conflicts: list[ConflictReport]
    forbidden_action_keys: list[str]
    retry_policy: list[str]              # 한국어 hint
```

## 5. 통신 토폴로지

워크스페이스 토폴로지 맵(`workspace_nodes` + `workspace_edges`)을 그대로 활용한다.

- `Building Battery Agent` ↔ `City Grid Coordinator` 양방향 edge.
- 빌딩 agent 간 직접 메시지 교환은 **하지 않는다.** 모든 inter-building 정보는 Coordinator의 mean-field summary를 거친다.
- 이는 통신량을 빌딩 수에 선형으로 묶고, 권한/감사 trail을 단순화한다.

```text
Building_1 ─┐                ┌─ feedback (mean_field, conflicts)
Building_2 ─┤                │
   ...      ├─► Coordinator ─┤─► Constraint Guard ─► approved actions
Building_17 ┘                └─ Summarizer (operator-facing)
```

## 6. Rollout Verification (논문 강조)

CoProposer가 낸 proposal은 즉시 적용 후보가 되지 않는다. 다음을 거친다.

```text
1. CoProposer가 self_action을 낸다.
2. SandboxExecutor가 self_action만 가상 적용 (single-building rollout, k=1)
3. ConstraintValidator가 SOC/range/building 존재 검증
4. 1차 통과한 proposal만 Negotiator로 올린다.
5. Negotiator가 전체 proposal을 합쳐 district-level rollout 재실행 (k=1~3)
6. 최종 plan만 Constraint Guard로 넘긴다.
```

`SandboxExecutor`는 Grid-Agent 쪽 구현을 그대로 재사용한다.

## 7. Mean-Field Summary 계산 규칙

MVP는 단순 평균/분산을 사용한다.

```python
def compute_mean_field(snapshot, neighbor_ids) -> MeanFieldSummary:
    buildings = [b for b in snapshot["buildings"] if b["building_id"] in neighbor_ids]
    loads = [b["agent_mesh_net_load_kwh"] for b in buildings]
    socs = [b["battery_soc"] for b in buildings]
    pvs = [b["pv_generation_kwh"] for b in buildings]
    critical = sum(1 for s in socs if s < 0.2 or s > 0.9) / max(1, len(socs))
    return MeanFieldSummary(
        time_step=snapshot["step"],
        avg_net_load_kwh=mean(loads),
        var_net_load_kwh=variance(loads),
        avg_battery_soc=mean(socs),
        avg_pv_generation_kwh=mean(pvs),
        district_peak_threshold=PEAK_THRESHOLD,
        critical_building_ratio=critical,
        weight_sum=sum_of_weights(buildings),
    )
```

이 객체 하나만 LLM prompt에 넣으면 raw state 전체를 보내지 않아도 의사결정이 가능해진다.

## 8. Semantic Gradient Descent 적용 방식

```text
1. 한 iteration(또는 한 step)이 끝나면 ConstraintValidator의 score_before/score_after를 본다.
2. score가 악화되었거나 approval rate가 떨어지는 경우에만 Introspector를 호출한다.
3. Introspector LLM에게 다음을 입력:
   - 직전 5 step의 (action, score_delta, violation_delta) trace
   - 현재 자연어 전략 (latest version)
4. 출력은 다음 JSON:
   {
     "new_strategy": "<한국어 자연어 규칙>",
     "diff_explanation": "<왜 바꾸는지>",
     "scope": "self_only | broadcasted"
   }
5. agent_strategy_versions 테이블에 versioning 저장.
6. 다음 Planner prompt 앞단에 latest strategy를 주입.
```

핵심 안전장치:
- 새 전략이 **다음 N step의 평균 score를 더 악화**시키면 이전 버전으로 rollback.
- 모든 전략 버전은 사람이 읽을 수 있어야 하며, 운영자가 수동으로 disable 가능.

## 9. 실패 사례 방지

논문이 강조하는 실패 패턴과 MeshBoard 대응:

| 실패 패턴 | MeshBoard 대응 |
| --- | --- |
| 수치/공간 hallucination (잘못된 building, 범위 외 action) | `validate_citylearn_battery_plan`이 schema + 존재 여부 + 범위 검증 |
| Agent identity confusion | 모든 prompt 앞에 `You are Building_X agent` 명시 + sender/receiver schema 강제 |
| Output 포맷 깨짐 | `agent_runtime.py`의 JSON 프로토콜 유지 + retry parser + AGENT_INVALID_RESPONSE_MESSAGE fallback |
| Negotiation 지연 (round 폭발) | `max_rounds=2`, `timeout_seconds=30`, fallback = deterministic heuristic |
| Token cost 폭발 | mean-field summary로 raw state 공유 차단, 작은 모델/큰 모델 역할 분리 |

## 10. Human-in-the-loop 통합

MACRO-LLM은 자동 협상에 가깝지만, MeshBoard는 운영자가 직접 관여한다.

추가 기능:
- 협상 trace를 Workspace Board의 메시지 뷰에 표시 (기존 Slack형 UI 그대로).
- Operator는 round 사이에 개입해 `forbidden_action_keys`를 수동 추가 가능.
- 특정 빌딩 agent를 일시 disable.
- 전략 버전 (semantic gradient)을 운영자가 승인/반려.

이 UX는 MACRO-LLM 원논문에는 없지만 MeshBoard 차별성으로 가져갈 만하다.

## 11. 본 논문에서 가져올 핵심

1. **빌딩 단위 분산 관측 + 빌딩 단위 proposal**로 수평적 확장성 확보.
2. **Mean-field summary**로 메시지 크기를 빌딩 수에 무관하게 유지.
3. **2-round negotiation**으로 단일 LLM call의 한계 보완.
4. **Semantic gradient descent**로 운영 중 전략 개선 (재학습 없이).
5. **Rollout verification**을 모든 proposal에 강제.

다음 문서 [`03_recommended_architecture.md`](./03_recommended_architecture.md)는
Grid-Agent와 MACRO-LLM을 하나의 워크플로우로 결합한 MeshBoard 통합 아키텍처를 다룬다.

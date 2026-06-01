# MACRO-LLM 논문 분석 및 구현 지침 정리

> 대상 논문: **MACRO-LLM: LLM-Empowered Multi-Agent Collaborative Reasoning under Spatiotemporal Partial Observability**  
> 목적: 논문의 핵심 개념을 이해하고, 이를 바탕으로 직접 에이전트 간 소통/협상 기반 아키텍처를 구현할 때 필요한 구조와 지침을 정리한다.

---

## 1. 논문 한 줄 요약

**MACRO-LLM은 분산된 여러 LLM 에이전트가 전체 상황을 다 보지 못하는 환경에서, 이웃 에이전트와 제안·협상·자기반성을 반복하며 더 안정적인 공동 의사결정을 하도록 만든 멀티에이전트 협업 프레임워크이다.**

---

## 2. 논문이 해결하려는 문제

### 2.1 기존 멀티에이전트 시스템의 한계

논문은 현실 세계의 에이전트들이 중앙 서버처럼 모든 정보를 다 볼 수 없다고 본다. 예를 들어 자율주행 차량, 도시 에너지 관리, 감염병 통제, 교통 시스템 같은 환경에서는 각 에이전트가 자기 주변의 일부 정보만 관측한다.

기존 방식의 한계는 크게 세 가지다.

1. **중앙집중형 구조의 병목**
   - 모든 정보를 중앙 노드에 모으는 방식은 이해하기 쉽지만, 에이전트 수가 많아질수록 통신량과 계산량이 커진다.
   - 중앙 노드가 고장나면 전체 시스템이 흔들릴 수 있다.

2. **완전 연결형 에이전트 그래프의 과도한 통신 비용**
   - 모든 에이전트가 모든 에이전트와 대화하면 정보는 많아지지만, 통신량이 폭발한다.
   - LLM context window도 금방 초과된다.

3. **MARL의 재학습 비용**
   - Multi-Agent Reinforcement Learning은 환경이 바뀌면 재학습이 필요할 수 있다.
   - 도시 관리처럼 상황이 자주 바뀌는 환경에서는 매번 학습하는 방식이 현실적으로 부담스럽다.

---

## 3. 핵심 문제 정의: Spatiotemporal Partial Observability

논문에서 가장 중요한 개념은 **Spatiotemporal Partial Observability**, 즉 **시공간적 부분 관측성**이다.

### 3.1 Spatial Partial Observability

**공간적 부분 관측성**은 각 에이전트가 전체 시스템이 아니라 자기 주변 일부만 볼 수 있는 문제다.

예시:

- 차량은 주변 차량 일부만 감지할 수 있음
- 건물 에너지 에이전트는 자기 건물과 근처 건물 정보만 알 수 있음
- 도시의 각 구역 에이전트는 전체 도시의 수요·공급·혼잡도를 다 알 수 없음

### 3.2 Temporal Partial Observability

**시간적 부분 관측성**은 에이전트가 과거 전체 이력과 미래 변화를 완전히 알 수 없는 문제다.

예시:

- 지금 에너지를 절약하면 3시간 뒤 피크 수요에 어떤 영향을 줄지 불확실함
- 지금 차량이 감속하면 뒤 차량들의 움직임이 어떻게 바뀔지 정확히 알기 어려움
- 도시 관리에서 돌발 이벤트가 장기적으로 어떤 영향을 미칠지 불확실함

### 3.3 왜 이 개념이 중요한가


도시관리 시스템에서 각 에이전트는 다음과 같은 제한을 가진다.

| 제한 | 예시 |
|---|---|
| 공간적 제한 | 특정 건물, 구역, 도로, 전력망 일부만 관측 |
| 시간적 제한 | 미래 수요, 사고, 기상 변화, 사용자 행동 예측 불확실 |
| 통신 제한 | 모든 에이전트가 모든 정보를 공유하면 비용 증가 |
| 의사결정 충돌 | 한 에이전트의 최적 행동이 다른 에이전트에게는 악영향 가능 |

---

## 4. MACRO-LLM 전체 아키텍처

논문은 각 에이전트를 세 개의 핵심 모듈로 구성한다.

```text
Agent n
├── CoProposer
│   └── 후보 행동 제안 + rollout 기반 검증
├── Negotiator
│   └── 이웃 에이전트와 협상 + 충돌 해결 + mean-field 집계
└── Introspector
    └── 실행 결과 반성 + semantic gradient descent 기반 전략 수정
```

전체 흐름은 다음과 같다.

```text
1. 환경 관측
2. 각 에이전트가 자기 관측과 목표를 바탕으로 후보 행동 생성
3. 후보 행동을 짧게 미래 시뮬레이션하여 검증
4. 이웃 에이전트들과 proposal 교환
5. 충돌 여부 평가
6. mean-field 통계 정보로 보이지 않는 주변 상황 추정
7. 협상을 통해 최종 행동 결정
8. 환경에 행동 적용
9. 보상/결과를 보고 전략 수정
10. 다음 time step 반복
```

---

## 5. 모듈 1: CoProposer

### 5.1 역할

**CoProposer는 에이전트가 “내가 지금 무엇을 해야 하고, 내 이웃들은 무엇을 하면 좋을지”를 제안하는 모듈이다.**

단순히 자기 행동만 고르는 것이 아니라, 주변 에이전트의 협력 행동까지 함께 제안한다.

예시:

```json
{
  "agent_id": "Building_A",
  "self_action": "reduce_hvac_power_by_10_percent",
  "neighbor_suggestions": {
    "Building_B": "shift_load_to_battery",
    "Building_C": "maintain_current_consumption"
  },
  "reason": "현재 A 구역 수요가 급증했으므로 인접 건물의 부하 분산이 필요함"
}
```

### 5.2 Temporal Strategy

Temporal Strategy는 장기 목표를 향한 단계적 계획이다.

도시 에너지 관리 예시:

```text
현재 목표:
- 전체 전력 피크를 낮춘다.
- 실내 쾌적도는 일정 수준 이상 유지한다.
- 돌발 수요 급증에 대비한다.

Temporal Strategy:
1. 지금은 HVAC 출력을 급격히 줄이지 않는다.
2. 먼저 배터리 사용 가능 건물부터 부하를 이동한다.
3. 2~3 step 뒤 수요가 안정되면 냉방 출력을 조정한다.
```

### 5.3 Spatial Strategy

Spatial Strategy는 공간적 연결 관계를 고려한 전략이다.

도시관리 예시:

```text
Building_A는 Building_B, Building_C와 전력망상 인접해 있다.
A가 부하를 낮추면 B의 배터리 방전 압력이 줄어들 수 있다.
C는 이미 쾌적도 하한에 가까우므로 추가 절감 대상으로 삼지 않는다.
```

### 5.4 Rollout-Simulated Verification

논문에서 중요한 포인트는 **LLM이 낸 행동을 바로 실행하지 않고, 짧은 미래 시뮬레이션으로 검증한다는 점**이다.

이 구조는 매우 중요하다. LLM은 그럴듯한 결정을 내릴 수 있지만, 실제 제약조건을 위반할 수 있다. 따라서 행동 후보를 만들고, 환경 모델 또는 규칙 기반 시뮬레이터로 검증해야 한다.

```text
후보 행동 생성
→ t+1 상태 예측
→ 제약조건 검사
→ 보상 추정
→ 문제가 있으면 행동 수정
→ 통과한 후보만 협상에 올림
```

### 5.5 구현 지침

CoProposer를 구현할 때는 LLM에게 모든 판단을 맡기면 안 된다.

추천 구조:

```python
class CoProposer:
    def generate_initial_proposal(self, observation, temporal_strategy, spatial_strategy):
        ...

    def rollout_verify(self, proposal, simulator, horizon_k):
        ...

    def revise_proposal(self, proposal, violation_report):
        ...
```

핵심 지침:

- LLM은 **후보 생성**에 사용한다.
- 제약조건 검증은 **코드/시뮬레이터**가 담당한다.
- rollout horizon `k`는 너무 길게 잡지 않는다.
- MVP에서는 `k=1~3` 정도가 현실적이다.
- 제약조건은 명시적으로 JSON schema로 관리한다.

---

## 6. 모듈 2: Negotiator

### 6.1 역할

**Negotiator는 여러 에이전트가 동시에 낸 제안이 충돌할 때 이를 조정하는 모듈이다.**

예를 들어 도시 에너지 관리에서 다음과 같은 충돌이 생길 수 있다.

```text
Building_A: B가 배터리를 방전해주면 좋겠다.
Building_B: 나는 지금 배터리를 아껴야 한다.
Building_C: A와 B 모두 부하를 낮춰야 한다.
```

이때 Negotiator는 각 proposal의 차이를 비교하고, 신뢰도와 통계적 주변 정보를 바탕으로 최종 의사결정을 조정한다.

---

### 6.2 Mean-Field Approximation

논문은 모든 에이전트의 원시 데이터를 다 주고받는 대신, 이웃 상태를 통계값으로 압축한다.

핵심 아이디어:

```text
모든 이웃의 상세 상태를 다 보내지 말고,
평균, 분산, 가중치 같은 요약 정보만 주고받자.
```

예시:

```json
{
  "mean_field_summary": {
    "avg_energy_demand": 0.72,
    "var_energy_demand": 0.08,
    "avg_battery_level": 0.41,
    "avg_comfort_margin": 0.18,
    "weight_sum": 4.7
  }
}
```

이렇게 하면 에이전트 수가 늘어나도 각 에이전트가 처리해야 할 메시지 크기를 어느 정도 일정하게 유지할 수 있다.

---

### 6.3 Proposal Confidence Assessment

Negotiator는 제안 간 차이를 계산한다.

예시:

```text
내 proposal과 이웃 proposal 비교:
- 같은 행동을 요구하는가?
- 목표가 충돌하는가?
- 제약조건 위반 위험이 있는가?
- 이웃의 상태 요약 정보와 일관적인가?
```

이를 바탕으로 confidence score를 계산한다.

```json
{
  "proposal_id": "P_B_12",
  "confidence": 0.73,
  "conflict_type": "battery_constraint",
  "reason": "B의 배터리 잔량이 낮아 A의 요청을 그대로 수용하기 어렵다."
}
```

---

### 6.4 Multi-Round Negotiation

논문에서는 CoProposer와 Negotiator가 한 번만 실행되는 것이 아니라 여러 라운드 반복된다.

```text
Round 1:
- 각자 제안
- 충돌 확인

Round 2:
- mean-field 정보 반영
- 제안 수정

Round 3:
- 최종 합의 또는 timeout
```

MVP에서는 무한 협상하면 안 된다.

추천 설정:

```text
max_rounds = 2 또는 3
timeout_seconds = 10~30초
consensus_threshold = task별 설정
fallback_policy = 안전한 보수적 행동
```

---

### 6.5 구현 지침

추천 구조:

```python
class Negotiator:
    def aggregate_mean_field(self, neighbor_states):
        ...

    def evaluate_conflicts(self, own_proposal, neighbor_proposals):
        ...

    def assign_confidence(self, proposals, mean_field_summary):
        ...

    def regenerate_proposal(self, own_proposal, weighted_neighbor_proposals):
        ...

    def decide_final_action(self, proposal_history):
        ...
```

핵심 지침:

- 모든 대화를 자연어로만 처리하지 말고, proposal은 JSON schema로 고정한다.
- 자연어 reasoning은 `reason`, `explanation`, `risk_analysis` 필드로 분리한다.
- 최종 행동은 반드시 enum/action schema 안에서만 선택하게 한다.
- 협상 실패 시 fallback action을 준비한다.

---

## 7. 모듈 3: Introspector

### 7.1 역할

**Introspector는 실행 결과를 보고 에이전트의 전략을 수정하는 자기반성 모듈이다.**

이 모듈은 단순 memory가 아니다. 논문에서는 reward 변화와 상태 변화의 크기를 바탕으로 전략 업데이트 강도를 조절한다.

---

### 7.2 Observation-Consistency-based Adaptive Learning Rate

논문은 환경 변화가 클수록 전략을 더 크게 바꿔야 한다고 본다.

개념적으로는 다음과 같다.

```text
이전 상태 변화와 현재 상태 변화가 비슷함
→ 환경이 안정적임
→ 전략을 조금만 수정

이전 상태 변화와 현재 상태 변화가 크게 다름
→ 환경이 급변함
→ 전략을 강하게 수정
```

도시관리 예시:

```text
평소:
전력 수요가 조금씩 증가
→ 전략 미세 조정

돌발상황:
특정 구역 정전, 폭염, 행사 발생
→ 기존 전략 폐기 후 재계획
```

---

### 7.3 Semantic Gradient Descent

논문에서 가장 흥미로운 표현 중 하나가 **Semantic Gradient Descent**다.

일반 딥러닝의 gradient가 숫자라면, 여기서 gradient는 자연어 피드백이다.

예시:

```text
기존 전략의 문제:
A 구역의 수요 급증을 과소평가했고, B 구역 배터리 제약을 충분히 반영하지 않았다.

수정 방향:
다음 step부터는 B의 배터리 잔량이 30% 이하일 때 B에게 부하 이전을 요청하지 말고,
C와 D의 쾌적도 여유를 먼저 확인하라.
```

즉, LLM이 “다음에는 어떤 방향으로 전략을 바꿀지”를 자연어 규칙으로 업데이트한다.

---

### 7.4 구현 지침

추천 구조:

```python
class Introspector:
    def compute_reward_gap(self, prev_reward, current_reward):
        ...

    def compute_scene_change_rate(self, prev_transition, current_transition):
        ...

    def generate_semantic_gradient(self, logs, reward_gap, strategies):
        ...

    def update_strategy(self, old_strategy, semantic_gradient, learning_rate):
        ...
```

핵심 지침:

- reward가 나빠졌을 때만 반성하게 하면 비용을 줄일 수 있다.
- 모든 로그를 LLM에 넣지 말고, 최근 N개 step만 요약해서 넣는다.
- 전략 업데이트는 versioning해야 한다.
- 잘못된 반성으로 전략이 망가질 수 있으므로 rollback 가능해야 한다.
- 업데이트된 전략은 사람이 읽을 수 있는 형태로 저장한다.

---

## 8. 네 프로젝트에 적용할 수 있는 아키텍처 설계안

너의 프로젝트가 **도시관리 시스템 + agentic mesh platform**이라면, 논문 구조를 다음처럼 변형할 수 있다.

```text
MeshBoard / Agentic Urban Management Platform
├── Environment Layer
│   ├── 도시 시뮬레이터
│   ├── 에너지 수요 데이터
│   ├── 건물 상태 데이터
│   └── 돌발상황 이벤트
│
├── Agent Layer
│   ├── Building Agent
│   ├── District Agent
│   ├── Energy Grid Agent
│   ├── Weather/Event Agent
│   └── Human Operator Agent
│
├── Agent Reasoning Layer
│   ├── CoProposer
│   ├── Negotiator
│   └── Introspector
│
├── Communication Layer
│   ├── Peer-to-peer message bus
│   ├── Proposal exchange
│   ├── Mean-field summary exchange
│   └── Conflict resolution protocol
│
├── Control Layer
│   ├── Action validator
│   ├── Constraint checker
│   ├── Rollout simulator
│   └── Fallback policy
│
└── Monitoring Layer
    ├── Topology visualization
    ├── Negotiation trace
    ├── Strategy version history
    ├── Reward dashboard
    └── Human approval interface
```

---

## 9. 직접 구현할 때 가장 중요한 설계 원칙

### 9.1 LLM은 “의사결정 후보 생성기”로 쓰고, 검증은 코드가 한다

LLM에게 직접 최종 제어권을 주면 위험하다.

추천 분리:

| 역할 | 담당 |
|---|---|
| 후보 행동 생성 | LLM |
| 제약조건 검증 | Python simulator / rules |
| 숫자 계산 | 코드 |
| 최종 action schema 확인 | validator |
| 전략 설명 | LLM |
| 로그 저장 | DB |

---

### 9.2 모든 메시지는 구조화해야 한다

나쁜 예:

```text
저는 지금 에너지를 조금 줄이는 게 좋다고 생각합니다.
```

좋은 예:

```json
{
  "sender": "Building_A",
  "receiver": "Building_B",
  "time_step": 12,
  "proposal_type": "load_shift_request",
  "target_action": "discharge_battery",
  "action_value": 0.15,
  "expected_effect": {
    "peak_reduction": 0.08,
    "comfort_risk": 0.02
  },
  "reason": "A구역 피크 수요가 상승하고 B는 배터리 여유가 있음"
}
```

---

### 9.3 자연어 reasoning과 실행 action을 분리해야 한다

LLM의 설명은 사람이 이해하기 좋지만, 시스템 실행은 명확한 action으로 해야 한다.

```json
{
  "reasoning": "현재 A 구역의 피크가 높고 B 구역의 배터리 여유가 있으므로...",
  "action": {
    "type": "ADJUST_HVAC",
    "target": "Building_A",
    "value": -0.1
  }
}
```

---

### 9.4 Negotiation timeout을 반드시 둬야 한다

협상이 길어지면 시스템이 느려진다.

추천:

```text
max_negotiation_rounds = 2~3
max_llm_calls_per_agent_per_step = 3~5
timeout = 10~30초
fallback = 안전 모드
```

---

### 9.5 Mean-field summary는 MVP에서 꼭 넣는 것이 좋다

이 논문의 핵심 차별점 중 하나는 “모든 raw state 공유”가 아니라 “통계적 요약 공유”다.

도시 에너지 관리용 mean-field 후보:

```json
{
  "avg_demand": 0.68,
  "demand_variance": 0.12,
  "avg_battery_soc": 0.44,
  "avg_comfort_margin": 0.21,
  "avg_carbon_intensity": 0.57,
  "critical_node_ratio": 0.18
}
```

---

### 9.6 Human-in-the-loop를 넣으면 네 프로젝트 차별성이 커진다

논문은 주로 agent 간 협상에 집중하지만, 너의 플랫폼은 도시관리 시스템이므로 사람이 개입할 수 있어야 한다.

추천 기능:

- 협상 결과 확인
- 에이전트 reasoning trace 보기
- 제안 승인/거절
- 특정 에이전트 강제 override
- 전략 버전 비교
- 돌발상황 시 수동 목표 변경



---

## 11. 추천 데이터 구조

### 11.1 Agent State

```json
{
  "agent_id": "Building_A",
  "time_step": 10,
  "local_observation": {
    "energy_demand": 0.72,
    "temperature": 27.1,
    "occupancy": 0.63,
    "battery_soc": 0.45,
    "comfort_margin": 0.22
  },
  "neighbors": ["Building_B", "Building_C"],
  "current_strategy": {
    "temporal": "피크 시간대에는 배터리와 HVAC 조정을 병행한다.",
    "spatial": "인접 건물의 comfort margin이 낮으면 부하 이전을 요청하지 않는다."
  }
}
```

### 11.2 Proposal

```json
{
  "proposal_id": "P_A_10_1",
  "sender": "Building_A",
  "time_step": 10,
  "self_action": {
    "type": "ADJUST_HVAC",
    "value": -0.1
  },
  "neighbor_actions": [
    {
      "target": "Building_B",
      "type": "DISCHARGE_BATTERY",
      "value": 0.15
    }
  ],
  "expected_outcome": {
    "peak_reduction": 0.08,
    "comfort_risk": 0.03
  },
  "confidence": 0.76,
  "reason": "A의 피크 수요가 증가했고 B는 배터리 여유가 있음"
}
```

### 11.3 Negotiation Record

```json
{
  "round": 2,
  "time_step": 10,
  "agent_id": "Building_A",
  "received_proposals": ["P_B_10_1", "P_C_10_1"],
  "conflicts": [
    {
      "type": "resource_conflict",
      "agents": ["Building_A", "Building_B"],
      "description": "A는 B의 배터리 방전을 요청했으나 B는 배터리 보존 전략을 제안함"
    }
  ],
  "final_action": {
    "type": "ADJUST_HVAC",
    "value": -0.05
  }
}
```

### 11.4 Strategy Version

```json
{
  "agent_id": "Building_A",
  "version": 4,
  "updated_at_step": 11,
  "learning_rate": 0.42,
  "semantic_gradient": "B의 배터리 제약을 과소평가했으므로, 향후 B의 SOC가 30% 이하일 때는 부하 이전 요청을 줄인다.",
  "new_temporal_strategy": "피크 대응 시 배터리 요청 전 SOC와 comfort margin을 먼저 확인한다."
}
```

---


## 13. 실험 설계 지침

네 프로젝트를 논문화하려면 단순 구현보다 실험 설계가 중요하다.

### 13.1 비교군

최소 비교군:

1. **Rule-based baseline**
   - 고정 규칙 기반 도시관리

2. **Centralized LLM**
   - 중앙 LLM 하나가 모든 정보를 받고 결정

3. **Independent LLM Agents**
   - 에이전트들이 협상 없이 각자 결정

4. **MACRO-style Agent Mesh**
   - proposal + negotiation + introspection 포함

### 13.2 Ablation Study

논문처럼 모듈 제거 실험을 해야 한다.

| 실험 | 제거 모듈 | 확인할 것 |
|---|---|---|
| Full | 없음 | 전체 성능 |
| w/o CoProposer | rollout 검증 제거 | 안전성/제약 위반 증가 여부 |
| w/o Negotiator | 협상 제거 | 충돌 증가 여부 |
| w/o Introspector | 자기반성 제거 | 장기 성능 저하 여부 |
| w/o Mean-field | 통계 요약 제거 | 확장성/통신량 악화 여부 |

### 13.3 평가 지표

도시 에너지 관리라면 다음 지표를 추천한다.

| 범주 | 지표 |
|---|---|
| 에너지 효율 | 총 에너지 사용량, peak demand, load variance |
| 안정성 | 제약 위반 횟수, comfort violation |
| 탄소 | CO2 배출량 추정, carbon intensity 기반 비용 |
| 협업 품질 | proposal conflict count, consensus rate |
| 효율성 | LLM call 수, token cost, decision latency |
| 확장성 | agent 수 증가에 따른 성능/비용 변화 |
| 돌발상황 대응 | recovery time, failure containment score |

---

## 14. 구현 시 주의할 실패 사례

논문 부록에서 언급되는 실패 사례는 실제 구현에서도 매우 중요하다.

### 14.1 산술/공간 hallucination

LLM은 숫자 계산이나 공간 관계를 틀릴 수 있다.

예시:

- 앞 차량과 뒤 차량을 혼동
- 이웃 노드 방향을 잘못 이해
- 전력 여유량 계산 오류
- 거리/부하/비율 계산 오류

대응:

- 숫자 계산은 Python으로 처리
- topology는 텍스트가 아니라 구조화된 graph로 제공
- 예시 기반 few-shot prompt 사용
- action 실행 전 validator 필수 적용

---

### 14.2 Agent identity confusion

에이전트가 자기 역할이나 상대 에이전트를 혼동할 수 있다.

대응:

- 모든 prompt 앞에 `You are Agent_X` 명시
- sender, receiver를 JSON schema로 강제
- message_id, proposal_id 사용
- self-consistency check 적용

---

### 14.3 Output format 오류

작은 모델은 XML/JSON 형식을 잘 깨뜨릴 수 있다.

대응:

- JSON schema validation
- retry parser
- function calling / structured output 사용
- 실패 시 fallback action 실행

---

### 14.4 협상 지연

라운드가 많아지면 latency와 비용이 증가한다.

대응:

- max_rounds 제한
- proposal 압축
- mean-field summary 사용
- 작은 모델과 큰 모델의 역할 분리
- 긴급 상황에서는 rule-based fallback 사용

---

## 15. 너의 캡스톤/논문에 맞춘 해석

이 논문을 네 프로젝트에 가져올 때 핵심은 다음과 같다.

### 15.1 그대로 따라 하면 안 되는 부분

- 논문의 CACC/감염병 통제 실험을 그대로 재현하려고 하면 범위가 커진다.
- GPT-4o 기반 다중 에이전트 협상을 모든 step에서 돌리면 비용이 커질 수 있다.
- 실제 도시관리에는 안전성과 검증 문제가 더 중요하므로 LLM 판단을 그대로 실행하면 안 된다.

### 15.2 가져오면 좋은 부분

- 시공간적 부분 관측성이라는 문제 정의
- 중앙집중형이 아닌 peer-to-peer agent graph
- proposal 기반 협상 구조
- rollout 검증
- mean-field 통계 요약
- semantic gradient descent 기반 전략 업데이트
- ablation study 설계 방식
- communication cost와 latency 분석 관점


---

## 16. 구현 체크리스트

### 기본 구조

- [ ] Agent class 구현
- [ ] Topology graph 구현
- [ ] Observation schema 정의
- [ ] Action schema 정의
- [ ] Proposal schema 정의
- [ ] Negotiation record schema 정의
- [ ] Strategy memory schema 정의

### CoProposer

- [ ] temporal strategy 생성
- [ ] spatial strategy 생성
- [ ] proposal 생성
- [ ] rollout simulator 연동
- [ ] constraint checker
- [ ] proposal revision

### Negotiator

- [ ] neighbor proposal 수집
- [ ] conflict detection
- [ ] mean-field summary 계산
- [ ] confidence scoring
- [ ] multi-round negotiation
- [ ] final action selection

### Introspector

- [ ] reward gap 계산
- [ ] transition vector 저장
- [ ] scene change rate 계산
- [ ] semantic gradient 생성
- [ ] strategy update
- [ ] strategy versioning

### 안전장치

- [ ] JSON schema validation
- [ ] timeout
- [ ] fallback policy
- [ ] retry parser
- [ ] human approval option
- [ ] log replay 기능

### 실험

- [ ] baseline 설정
- [ ] ablation study
- [ ] agent 수 변화 실험
- [ ] 돌발상황 시나리오
- [ ] latency/token cost 측정
- [ ] 성능 지표 dashboard

---

## 17. 추천 구현 순서

가장 현실적인 순서는 다음과 같다.

```text
1. 도시관리 문제를 단순화한다.
   예: 5개 건물의 에너지 피크 제어

2. 각 건물을 Agent로 만든다.

3. 각 Agent가 자기 상태만 보게 만든다.

4. 이웃 Agent와 proposal을 주고받게 만든다.

5. LLM proposal을 JSON으로 생성한다.

6. rule-based validator로 proposal을 검증한다.

7. 2-round negotiation을 구현한다.

8. 최종 action을 simulator에 반영한다.

9. reward와 로그를 저장한다.

10. Introspector로 전략 업데이트를 붙인다.

11. dashboard에서 topology와 negotiation trace를 보여준다.

12. baseline과 비교 실험한다.
```

---

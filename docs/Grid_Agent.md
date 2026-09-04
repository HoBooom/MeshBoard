# Grid-Agent 논문 분석 및 구현 지침

> 분석 대상: **Semantic Reasoning Meets Numerical Precision: An LLM-Powered Multi-Agent System for Power Grid Control**  
> 핵심 주제: 전력망 제어 문제에서 **LLM 기반 의미론적 추론**과 **수치 시뮬레이션/전력조류 해석의 정확성**을 결합한 멀티 에이전트 시스템

---

## 1. 논문 한 줄 요약

이 논문은 전력망에서 발생하는 전압 위반, 선로 과부하, 버스 단절 등의 문제를 해결하기 위해, **LLM이 전략을 세우고**, **전력망 시뮬레이터가 수치적으로 검증하며**, **검증 실패 시 롤백하는** 멀티 에이전트 기반 전력망 제어 프레임워크인 **Grid-Agent**를 제안한다.

---

## 2. 문제 배경

현대 전력망은 다음과 같은 이유로 기존 제어 방식만으로 관리하기 어려워지고 있다.

- 분산 에너지 자원, 즉 태양광·풍력·ESS 등의 증가
- 전기차 보급 확대에 따른 부하 변동성 증가
- 극한 기상 현상 증가
- 노후화된 전력 인프라
- 복잡한 배전망/송전망 구조
- 실시간 장애 대응 필요성 증가

기존 방식은 크게 두 가지로 나눌 수 있다.

### 2.1 규칙 기반 시스템

운영자가 미리 정의한 규칙에 따라 제어한다.

예시:

- 전압이 낮으면 배터리 투입
- 선로 과부하가 발생하면 부하 차단
- 고장 선로가 있으면 스위치 개방

장점은 안정적이고 설명 가능하다는 점이다.  
하지만 예외 상황, 복합 장애, 새로운 네트워크 구조에는 약하다.

### 2.2 수치 최적화 기반 시스템

Optimal Power Flow, OPF 같은 최적화 기법을 사용한다.

장점은 물리 법칙과 수학적 제약을 엄밀하게 반영할 수 있다는 점이다.  
하지만 현대 전력망 문제는 다음 특성을 갖기 때문에 계산이 어려워진다.

- mixed-integer
- nonlinear
- non-convex
- unbalanced AC optimal power flow
- discrete control과 continuous control이 함께 존재

즉, 이론적으로는 강력하지만 실제 복잡한 운영 환경에서는 계산 비용과 수렴 문제가 크다.

---

## 3. 논문의 핵심 아이디어

논문의 핵심은 다음 문장으로 정리할 수 있다.

> LLM은 전력망 상황을 해석하고 전략을 세우되, 실제 제어 가능성과 안정성은 반드시 전력망 시뮬레이터로 검증한다.

즉, LLM을 직접 제어기로 쓰는 것이 아니다.

LLM은 다음 역할을 한다.

- 현재 전력망 상태를 이해한다.
- 어떤 위반이 중요한지 판단한다.
- 어떤 제어 액션 조합이 효과적일지 추론한다.
- 여러 제어 방법을 조합해 전략을 세운다.
- 결과를 사람이 이해할 수 있게 설명한다.

반면, 실제 수치 검증은 다음 도구가 담당한다.

- power flow solver
- sandbox simulation
- validation module
- rollback mechanism

이 구조는 LLM의 장점과 수치 해석 도구의 장점을 분리해서 결합한다는 점에서 의미가 있다.

---

## 4. Grid-Agent의 전체 구조

Grid-Agent는 크게 5개의 에이전트로 구성된다.

```text
Topology Agent
      ↓
Planner Agent
      ↓
Executor Agent
      ↓
Validator Agent
      ↓
Summarizer Agent
      ↺ 실패 시 다시 Planner Agent로 피드백
```

논문에서는 이를 **state-driven multi-agent workflow**로 설명한다.  
각 에이전트는 하나의 거대한 LLM이 모든 것을 처리하는 방식이 아니라, 역할별로 분리되어 있다.

---

## 5. 에이전트별 역할 정리

## 5.1 Topology Agent

### 역할

전력망의 구조와 초기 상태를 파악하는 에이전트다.

### 입력

- bus 정보
- line 정보
- load 정보
- generator 정보
- switch 상태
- transformer 정보
- 전압/전류/전력 흐름
- 현재 위반 목록

### 출력

- 네트워크 토폴로지 표현
- 현재 violation report
- 제어 가능한 자산 목록
- Planner Agent가 이해할 수 있는 구조화된 상태

### 구현 관점

직접 구현할 때는 Topology Agent가 단순히 LLM일 필요는 없다.  
오히려 초기 MVP에서는 Python 코드 기반 파서로 구현하는 것이 더 안정적이다.

예시 구현:

```python
class TopologyAgent:
    def analyze(self, network):
        violations = detect_violations(network)
        topology_summary = serialize_network(network)
        controllable_assets = find_controllable_assets(network)
        return {
            "violations": violations,
            "topology": topology_summary,
            "controllable_assets": controllable_assets
        }
```

---

## 5.2 Planner Agent

### 역할

LLM 기반 핵심 추론 에이전트다.

현재 전력망 상태와 위반 목록을 보고, 어떤 조치를 어떤 순서로 수행할지 계획한다.

### 주요 액션

논문에서 다루는 대표적인 액션은 다음과 같다.

1. **Switch Operation**
   - 스위치를 열거나 닫아 전력 흐름을 재구성한다.

2. **Battery Placement / Dispatch**
   - 특정 버스에 배터리를 배치하거나, 배터리의 유효전력/무효전력 출력을 조절한다.

3. **Load Curtailment**
   - 일부 부하를 줄여 전력망 안정성을 확보한다.

### 중요한 점

Planner Agent는 자연어 답변을 하면 안 된다.  
반드시 기계가 파싱 가능한 형식으로 응답해야 한다.

예시:

```json
[
  {
    "tool": "update_switch_status",
    "args": {
      "line_id": "L12",
      "status": "open"
    },
    "reason": "Line L12 is causing downstream overload."
  },
  {
    "tool": "add_battery",
    "args": {
      "bus_id": 18,
      "p_mw": 0.5,
      "q_mvar": 0.2
    },
    "reason": "Battery injection can improve voltage at nearby buses."
  }
]
```

### 구현 지침

Planner 프롬프트에는 반드시 다음이 포함되어야 한다.

- 역할 정의
- 현재 네트워크 상태
- 위반 목록
- 사용 가능한 액션 목록
- 액션별 제약 조건
- 우선순위 정책
- 출력 JSON schema
- 금지 행동
- 실패 시 재계획 방식

---

## 5.3 Executor Agent

### 역할

Planner가 만든 추상적 계획을 실제 시뮬레이터 API 호출로 바꾸는 에이전트다.

예를 들어 Planner가 다음 계획을 냈다고 하자.

```json
{
  "tool": "curtail_load",
  "args": {
    "bus_id": 25,
    "curtailment_ratio": 0.1
  }
}
```

Executor는 이를 실제 pandapower 또는 전력망 시뮬레이션 코드로 변환한다.

예시:

```python
def curtail_load(net, bus_id, ratio):
    load_indices = net.load[net.load.bus == bus_id].index
    for idx in load_indices:
        net.load.at[idx, "p_mw"] *= (1 - ratio)
```

### 중요한 점

Executor는 live network에 바로 적용하면 안 된다.  
반드시 sandbox copy에 적용해야 한다.

```python
net_working = copy.deepcopy(net_original)
```

즉, Executor의 핵심 원칙은 다음이다.

> 제안된 조치는 항상 복사본에서 먼저 실행하고, 검증된 뒤에만 승인한다.

---

## 5.4 Validator Agent

### 역할

Executor가 실행한 조치가 실제로 안전하고 효과적인지 검증한다.

### 검증 항목

- 기존 violation이 해결되었는가?
- 새로운 violation이 생기지 않았는가?
- power flow가 수렴하는가?
- 전압 범위가 정상인가?
- 선로 과부하가 해소되었는가?
- 단절된 bus가 복구되었는가?
- 액션 수가 과도하지 않은가?
- 부하 차단 같은 disruptive action이 불필요하게 사용되지 않았는가?

### 구현 지침

Validator는 LLM보다 수치 코드 중심으로 구현해야 한다.

```python
class ValidatorAgent:
    def validate(self, net_before, net_after):
        try:
            run_power_flow(net_after)
        except PowerFlowNotConverged:
            return {
                "approved": False,
                "reason": "Power flow did not converge."
            }

        violations_before = detect_violations(net_before)
        violations_after = detect_violations(net_after)

        if len(violations_after) < len(violations_before):
            return {
                "approved": True,
                "violations_after": violations_after
            }

        return {
            "approved": False,
            "reason": "No improvement or worsened state."
        }
```

---

## 5.5 Summarizer Agent

### 역할

성공한 제어 과정을 사람이 이해할 수 있게 설명하고, 향후 학습 데이터로 저장한다.

### 출력

- 초기 상태 요약
- 발생한 violation
- 수행한 action sequence
- 각 action의 이유
- 최종 결과
- 해결된 violation
- 남은 위험 요소
- 학습 데이터 포맷

### 예시 출력

```markdown
## Resolution Summary

Initial violations:
- Bus 18 undervoltage
- Line 12 overload
- Bus 22 disconnected

Actions taken:
1. Opened switch L12 to reroute overloaded flow.
2. Added battery at Bus 18 to support voltage.
3. Closed tie switch L19 to restore disconnected buses.

Result:
- All voltage violations resolved.
- Thermal overload removed.
- Disconnected buses restored.
```

### 구현 관점

Summarizer는 실험 결과를 사람이 읽을 수 있게 만드는 부분이라 보고서 작성에 중요하다.  
왜냐하면 시스템의 판단 과정을 설명 가능한 형태로 남기기 때문이다.

---

## 6. Grid-Agent의 핵심 기술 구조

## 6.1 LLM + Tool Use 구조

이 논문의 핵심은 LLM이 직접 계산하지 않는다는 점이다.

LLM은 다음을 한다.

- 문제 해석
- 전략 수립
- 액션 선택
- 액션 조합
- 결과 설명

도구는 다음을 한다.

- power flow 계산
- violation detection
- sandbox execution
- rollback
- metric calculation

즉, 구조는 다음과 같다.

```text
LLM reasoning
    ↓ tool call
Numerical simulator
    ↓ result
LLM replanning / summarization
```

이 구조는 네가 에이전트 아키텍처를 구현할 때도 매우 중요하다.

LLM에게 모든 것을 맡기면 안 된다.  
반드시 검증 가능한 외부 도구와 결합해야 한다.

---

## 6.2 Sandboxed Execution

전력망처럼 안전이 중요한 시스템에서는 제안된 action을 실제 시스템에 바로 적용하면 위험하다.

따라서 논문은 sandboxed execution을 강조한다.

구현 구조:

```text
Original Network
      ↓ copy
Sandbox Network
      ↓ apply actions
Power Flow Validation
      ↓
Approve or Rollback
```

MVP에서는 실제 전력망이 아니라 시뮬레이션 네트워크를 사용하더라도 이 개념은 반드시 유지하는 것이 좋다.

---

## 6.3 Rollback Mechanism

Rollback은 실패한 조치를 되돌리는 장치다.

논문에서는 Validator가 조치 후 네트워크 상태가 개선되지 않았다고 판단하면 sandbox 상태를 이전으로 되돌린다.

구현 방식:

```python
checkpoint = copy.deepcopy(net_working)

apply_actions(net_working, actions)

if not validate(net_working):
    net_working = checkpoint
```

주의할 점:

- action 단위 rollback
- plan 단위 rollback
- iteration 단위 rollback

중 어떤 수준으로 되돌릴지 정해야 한다.

MVP에서는 plan 단위 rollback이 가장 단순하다.

---

## 6.4 Adaptive Multi-Scale Network Representation

LLM은 컨텍스트 길이에 제한이 있다.  
전력망 전체 정보를 그대로 넣으면 토큰이 과도하게 커진다.

논문은 네트워크 크기에 따라 표현 방식을 다르게 선택한다.

### 작은 네트워크

모든 component를 자세히 직렬화한다.

```text
Bus 1: voltage = 1.02 pu
Bus 2: voltage = 0.91 pu
Line 1-2: loading = 85%
...
```

### 큰 네트워크

전체를 다 넣지 않고, violation 주변 정보 중심으로 요약한다.

```text
Violation cluster A:
- affected buses: 15, 16, 17
- nearby controllable assets: switch S3, battery candidate bus 18
- upstream feeder: line 8-12
```

### 구현 지침

처음부터 복잡한 adaptive representation을 만들 필요는 없다.  
하지만 다음 3단계 구조는 설계해두는 것이 좋다.

1. Full representation
2. Violation-centric representation
3. Cluster-based semantic graph representation

---

## 6.5 Coordinated Action Optimization

논문에서 중요한 지점은 violation을 하나씩 고치는 것이 아니라, 여러 violation을 동시에 해결하는 action을 찾는다는 점이다.

예를 들어 Bus 20, 21, 22의 저전압을 각각 따로 해결하는 대신, 하나의 switch operation으로 downstream 전압 문제를 한 번에 해결할 수 있다.

이것이 논문에서 말하는 coordinated action planning의 의미다.

### 구현 지침

Planner에게 다음 기준을 명시해야 한다.

- 하나의 action으로 여러 violation을 해결할 수 있는지 먼저 고려
- topology reconfiguration을 우선 고려
- battery action은 두 번째로 고려
- load curtailment는 마지막 수단으로 사용
- action 수를 최소화
- disruptive action을 최소화

---

## 7. 수학적/기술적 문제 정의

## 7.1 전력망 그래프 표현

논문은 전력망을 그래프로 정의한다.

```text
G = (N, E)
```

- N: bus 집합
- E: line/transformer 집합

각 bus에는 다음 상태가 있다.

- voltage magnitude
- voltage angle
- active power
- reactive power

각 line에는 다음 상태가 있다.

- current flow
- apparent power flow
- loading percentage

---

## 7.2 Violation 유형

논문에서 다루는 violation은 크게 세 가지다.

### 1. Voltage Violation

전압이 허용 범위를 벗어난 경우다.

```text
V_i < V_min 또는 V_i > V_max
```

### 2. Thermal Violation

선로 전류 또는 apparent power가 한계를 초과한 경우다.

```text
S_ij > S_ij_max 또는 I_ij > I_ij_max
```

### 3. Disconnected Bus

버스가 주 전력망에서 전기적으로 고립된 경우다.

---

## 7.3 목적 함수

논문은 제어 action sequence를 찾는 문제를 다음처럼 표현한다.

```text
minimize Σ c(a_t) + λ|A|
```

의미는 다음과 같다.

- c(a_t): 각 action의 비용
- |A|: action 개수
- λ: action 수를 줄이기 위한 penalty

즉, 목표는 단순히 violation을 해결하는 것이 아니라,

> 가능한 적은 수의, 덜 disruptive한 action으로 문제를 해결하는 것

이다.

---

## 8. 직접 구현할 때 추천 아키텍처

## 8.1 MVP 수준 구현 구조

처음 구현한다면 다음 구조가 현실적이다.

```text
Frontend
  - 시나리오 선택
  - 현재 violation 확인
  - 해결 과정 시각화
  - 최종 explanation 표시

Backend API
  - /analyze
  - /plan
  - /execute
  - /validate
  - /summarize

Core Engine
  - TopologyAgent
  - PlannerAgent
  - ExecutorAgent
  - ValidatorAgent
  - SummarizerAgent

Simulation Layer
  - pandapower
  - networkx
  - custom violation detector

Storage Layer
  - scenario logs
  - action logs
  - validation results
  - successful trajectories
```

---

## 8.2 권장 기술 스택

### Backend

- Python
- FastAPI
- Pydantic
- pandapower
- networkx
- LangGraph 또는 자체 state machine
- PostgreSQL 또는 SQLite

### LLM

- OpenAI API
- Claude API
- Gemini API

처음에는 하나의 LLM만 사용해도 충분하다.  
다만 논문처럼 모델별 비교를 하려면 provider interface를 분리하는 것이 좋다.

```python
class LLMProvider:
    def generate_plan(self, prompt: str) -> list[Action]:
        pass
```

### Frontend

- Next.js
- React Flow
- Tailwind CSS
- Recharts

### Visualization

- networkx layout
- React Flow
- D3.js
- Plotly

---

## 8.3 LangGraph 기반 구현 구조

이 논문은 워크플로우가 명확하므로 LangGraph와 잘 맞는다.

```text
START
  ↓
TopologyAgent
  ↓
PlannerAgent
  ↓
ExecutorAgent
  ↓
ValidatorAgent
  ↓
if success:
    SummarizerAgent
else:
    PlannerAgent
```

조건부 edge:

```python
def route_after_validation(state):
    if state["validation"]["approved"]:
        return "summarizer"
    elif state["iteration"] >= state["max_iter"]:
        return "failed"
    else:
        return "planner"
```

---

## 9. 핵심 데이터 구조 설계

## 9.1 Violation 객체

```python
class Violation(BaseModel):
    type: Literal["voltage", "thermal", "disconnected"]
    target_id: str
    severity: float
    current_value: float | None
    limit_value: float | None
    description: str
```

## 9.2 Action 객체

```python
class Action(BaseModel):
    tool: Literal[
        "update_switch_status",
        "add_battery",
        "dispatch_battery",
        "curtail_load"
    ]
    args: dict
    reason: str
    expected_effect: str
```

## 9.3 Plan 객체

```python
class Plan(BaseModel):
    actions: list[Action]
    strategy_summary: str
    risk_assessment: str
```

## 9.4 ValidationResult 객체

```python
class ValidationResult(BaseModel):
    approved: bool
    resolved_violations: list[Violation]
    remaining_violations: list[Violation]
    new_violations: list[Violation]
    power_flow_converged: bool
    score_before: float
    score_after: float
    feedback: str
```

## 9.5 WorkflowState 객체

```python
class WorkflowState(BaseModel):
    network_id: str
    iteration: int
    max_iterations: int
    current_network: Any
    original_network: Any
    violations: list[Violation]
    action_history: list[Action]
    validation_history: list[ValidationResult]
    planner_feedback: str | None
```

---

## 10. 프롬프트 설계 지침

## 10.1 Planner Prompt 구성

Planner prompt는 다음 구조를 갖는 것이 좋다.

```text
You are an expert power system operator.

Goal:
Resolve all grid violations with minimal and safe control actions.

Current Network State:
{network_state}

Detected Violations:
{violations}

Available Actions:
1. update_switch_status(line_id, status)
2. add_battery(bus_id, p_mw, q_mvar)
3. curtail_load(bus_id, curtailment_ratio)

Operational Policy:
1. Prefer topology reconfiguration first.
2. Use battery deployment/dispatch second.
3. Use load curtailment only as a last resort.
4. Minimize the total number of actions.
5. Do not propose actions outside the available action space.
6. Avoid actions likely to create new violations.

Output Format:
Return only valid JSON.
```

---

## 10.2 Validator Feedback Prompt

실패한 경우 Planner에게 다음 피드백을 제공한다.

```text
The previous plan failed validation.

Reason:
{validation_feedback}

Remaining violations:
{remaining_violations}

New violations:
{new_violations}

Please generate a revised plan.
Do not repeat the exact same failed action sequence.
```

---

## 11. 평가 지표 설계

논문에서 사용한 평가 지표는 다음과 같다.

## 11.1 Success Rate

전체 시나리오 중 violation을 완전히 해결한 비율이다.

```text
success_rate = solved_scenarios / total_scenarios
```

## 11.2 Action Efficiency

하나의 action이 평균적으로 몇 개의 violation을 해결했는지 측정한다.

```text
action_efficiency = resolved_violations / number_of_actions
```

이 지표는 매우 중요하다.  
단순히 성공했는지가 아니라, 얼마나 전략적으로 해결했는지를 보여준다.

## 11.3 Convergence Speed

해결까지 걸린 planning-execution-validation iteration 수다.

## 11.4 Runtime

최종 해결까지 걸린 wall-clock time이다.

## 11.5 Solution Quality

정성적 지표지만 다음 기준으로 정량화할 수 있다.

- action 수가 적을수록 좋음
- load curtailment 사용이 적을수록 좋음
- 새로운 violation이 없을수록 좋음
- power flow 수렴성이 높을수록 좋음
- 해결 후 안정 margin이 클수록 좋음

---

## 12. 구현 시 반드시 고려해야 할 사항

## 12.1 LLM hallucination 방지

LLM은 존재하지 않는 bus, line, switch를 제안할 수 있다.

해결 방법:

- available action list를 명확히 제공
- 사용 가능한 asset ID만 prompt에 제공
- output schema validation
- tool call 전 존재 여부 검사
- 잘못된 action은 Executor에서 거부

---

## 12.2 안전성

전력망 제어 문제에서는 안전성이 최우선이다.

반드시 포함해야 할 장치:

- sandbox execution
- power flow convergence check
- post-action violation detection
- rollback
- max iteration limit
- forbidden action rule
- human approval option

---

## 12.3 비용 관리

LLM 기반 multi-agent 시스템은 token 비용이 커질 수 있다.

비용 절감 방법:

- 전체 네트워크를 매번 넣지 않기
- violation 주변 정보만 넣기
- action history를 요약해서 넣기
- structured JSON 사용
- 작은 모델과 큰 모델을 역할별로 분리
- 실패한 경우에만 큰 모델 호출

---

## 12.4 실시간성

논문 실험에서는 runtime도 평가한다.  
실제 운영에서는 수 초~수십 초 지연도 문제가 될 수 있다.

구현 시 고려할 점:

- power flow solver 속도
- LLM 응답 시간
- iteration 횟수 제한
- 병렬 검증 가능성
- 캐싱
- action 후보를 한 번에 여러 개 생성

---

## 12.5 설명 가능성

전력망 제어는 사람이 이해할 수 있어야 한다.

따라서 Summarizer Agent는 단순 요약이 아니라 다음을 설명해야 한다.

- 왜 이 action을 선택했는가?
- 어떤 violation을 해결하려는가?
- 왜 다른 action보다 안전한가?
- 해결 후 상태가 어떻게 바뀌었는가?
- 남은 위험은 무엇인가?

---

## 13. 네 프로젝트에 적용할 수 있는 포인트

네가 구상 중인 에이전틱 메쉬/도시 에너지 관리 프로젝트에 이 논문은 상당히 직접적으로 연결된다.

## 13.1 가져올 수 있는 핵심 구조

- LLM이 high-level planner 역할
- 수치 시뮬레이터가 validator 역할
- sandbox 기반 action 검증
- 실패 시 rollback
- 성공 사례를 dataset으로 축적
- 네트워크 크기에 따른 adaptive representation
- action efficiency 지표 사용
- 설명 가능한 action sequence 생성

## 13.2 도시 에너지 관리로 확장할 경우

전력망 대신 다음 상태를 다룰 수 있다.

- 건물별 에너지 수요
- ESS 상태
- 태양광 발전량
- 전기차 충전 수요
- 탄소 배출량
- 전력 요금
- grid stress level
- comfort level

제어 action은 다음과 같이 바꿀 수 있다.

- ESS charge/discharge
- HVAC setpoint adjustment
- EV charging delay
- demand response request
- load shifting
- building-level curtailment
- microgrid islanding

## 13.3 네 아키텍처에서의 대응 관계

| Grid-Agent 논문 | 네 프로젝트 적용 |
|---|---|
| Topology Agent | 도시/건물/에너지 네트워크 상태 분석 |
| Planner Agent | 에너지 제어 전략 생성 |
| Executor Agent | 시뮬레이터 또는 제어 API 실행 |
| Validator Agent | 에너지 비용/탄소/comfort violation 검증 |
| Summarizer Agent | 운영자용 설명 및 보고서 생성 |
| Power flow solver | CityLearn, EnergyPlus, custom simulator |
| Violation | 과부하, 비용 증가, 온도 불편, 탄소 초과 |
| Rollback | 잘못된 제어 전략 폐기 |
| Continuous learning | 성공 제어 사례 저장 및 fine-tuning/RAG |

---

## 14. 직접 구현할 때 단계별 로드맵

## Phase 1. 단일 시나리오 MVP

목표: 하나의 전력망/에너지 시나리오에서 violation을 감지하고 LLM이 action을 제안하게 만들기

구현 내용:

- pandapower 예제 네트워크 로딩
- voltage/thermal violation detector 구현
- Planner Agent prompt 작성
- JSON action output 받기
- action schema validation

---

## Phase 2. Sandbox + Validation

목표: 제안된 action을 sandbox에서 실행하고 검증하기

구현 내용:

- network deepcopy
- action executor 구현
- runpp 실행
- validation result 생성
- rollback 구현

---

## Phase 3. Multi-Agent Workflow

목표: Topology, Planner, Executor, Validator, Summarizer를 분리하기

구현 내용:

- agent class 분리
- workflow state 정의
- LangGraph 또는 자체 FSM 구현
- 실패 시 replanning loop 구현

---

## Phase 4. Adaptive Representation

목표: 작은 네트워크와 큰 네트워크에 서로 다른 prompt context 제공하기

구현 내용:

- full serialization
- violation-centric serialization
- controllable asset filtering
- graph clustering
- prompt token length 관리

---

## Phase 5. Experiment

목표: 보고서에 인용할 수 있는 실험 결과 확보하기

구현 내용:

- 여러 violation scenario 자동 생성
- LLM별 성능 비교
- action efficiency 측정
- success rate 측정
- runtime 측정
- failure case 분석

---

## Phase 6. UI / Dashboard

목표: 사람이 이해할 수 있는 에이전트 기반 제어 플랫폼 만들기

구현 내용:

- network graph visualization
- violation 표시
- action sequence 표시
- before/after 비교
- agent reasoning log 표시
- final explanation 표시

---

## 15. 구현 시 피해야 할 실수

## 15.1 LLM에게 수치 계산을 맡기기

LLM은 전력조류 계산을 직접 하면 안 된다.  
반드시 solver에게 맡겨야 한다.

## 15.2 자연어 출력만 받기

자연어 출력은 Executor가 처리하기 어렵다.  
반드시 JSON schema를 강제해야 한다.

## 15.3 검증 없이 action 적용하기

LLM이 제안한 action은 틀릴 수 있다.  
무조건 sandbox에서 검증해야 한다.

## 15.4 너무 큰 네트워크를 통째로 prompt에 넣기

토큰 낭비와 성능 저하가 발생한다.  
violation 중심으로 정보를 줄여야 한다.

## 15.5 성공 여부만 평가하기

성공률만 보면 부족하다.  
action efficiency, runtime, iteration, disruptive action 비율을 함께 봐야 한다.

---

## 16. 네가 논문/캡스톤으로 발전시킬 수 있는 방향

## 방향 1. LLM 기반 도시 에너지 제어 에이전트

Grid-Agent 구조를 도시 에너지 관리 문제에 적용한다.

핵심 contribution:

- 전력망 대신 도시 에너지 네트워크에 적용
- rule-based/RL 기반 시스템의 한계 보완
- 자연어 기반 설명 가능한 제어 전략
- simulation-based validation

---

## 방향 2. Agentic Mesh 기반 에너지 운영 플랫폼

여러 건물/지역/자산 에이전트가 서로 통신하고 협상하는 구조로 확장한다.

핵심 contribution:

- 중앙집중 planner가 아니라 분산 agent mesh 구조
- 건물별 agent가 local state를 보고 제안
- validator가 global constraint 검증
- human operator가 topology와 reasoning log를 확인

---

## 방향 3. LLM Planner + RL Controller 하이브리드

논문 Discussion에서 언급한 방향처럼, LLM은 high-level strategy를 만들고 RL은 continuous time-series control을 담당하게 한다.

예시:

- LLM: “향후 1시간 동안 ESS로 피크를 완화하라”
- RL: 5분 단위 ESS 충방전 스케줄 생성

---

## 17. 최소 구현 예시 흐름

```text
1. IEEE 30-bus network 로드
2. 일부 line/loading 또는 load를 조작해 violation 생성
3. TopologyAgent가 violation 탐지
4. PlannerAgent가 JSON action plan 생성
5. ExecutorAgent가 sandbox network에 action 적용
6. ValidatorAgent가 power flow 재실행
7. violation 감소 여부 확인
8. 실패 시 rollback 후 Planner 재호출
9. 성공 시 SummarizerAgent가 해결 과정 요약
10. action trajectory를 dataset으로 저장
```

---

## 18. 최종 구현 체크리스트

### 시스템 구조

- [ ] Agent별 역할이 분리되어 있는가?
- [ ] workflow state가 명확히 정의되어 있는가?
- [ ] 실패 시 재계획 loop가 있는가?
- [ ] max iteration 제한이 있는가?

### 안전성

- [ ] sandbox copy에서만 action을 실행하는가?
- [ ] power flow convergence check가 있는가?
- [ ] 새로운 violation을 탐지하는가?
- [ ] rollback이 구현되어 있는가?

### LLM 사용

- [ ] output schema를 강제하는가?
- [ ] 존재하지 않는 asset ID를 막는가?
- [ ] action space를 제한하는가?
- [ ] 실패 피드백을 prompt에 반영하는가?

### 실험

- [ ] success rate를 측정하는가?
- [ ] action efficiency를 측정하는가?
- [ ] runtime을 측정하는가?
- [ ] iteration 수를 측정하는가?
- [ ] failure case를 분석하는가?

### 보고서

- [ ] architecture diagram이 있는가?
- [ ] before/after violation 비교가 있는가?
- [ ] agent reasoning log가 있는가?
- [ ] baseline과 비교했는가?
- [ ] 한계와 개선 방향을 명확히 적었는가?

---

## 19. 이 논문의 한계

논문 자체도 다음 한계를 가진다.

1. 실제 운영망이 아니라 표준 테스트 네트워크 기반 실험이다.
2. LLM 응답의 안정성과 재현성 문제가 남아 있다.
3. 실시간 제어에는 latency 문제가 있을 수 있다.
4. 작은 모델은 복잡한 시나리오에서 실패율이 높다.
5. live grid 적용을 위해서는 human-in-the-loop가 필요하다.
6. cyber-attack이나 adversarial scenario에 대한 검증은 제한적이다.
7. 대규모 수천 bus 네트워크에서는 추가적인 hierarchical representation이 필요하다.

---

## 20. 요약

Grid-Agent 논문은 LLM 기반 멀티 에이전트 시스템을 전력망 제어 문제에 적용한 사례다.

핵심은 다음 네 가지다.

1. **LLM은 전략을 세운다.**
2. **수치 시뮬레이터는 검증한다.**
3. **실패한 전략은 rollback한다.**
4. **성공 사례는 학습 데이터로 축적한다.**

네가 직접 아키텍처를 구현한다면 이 논문의 핵심을 그대로 모방하기보다, 다음 원칙을 가져가는 것이 좋다.

> LLM을 제어기가 아니라 “설명 가능한 전략 생성기”로 쓰고, 실제 안전성과 성능은 검증 가능한 시뮬레이터와 규칙 기반 validator로 보장한다.

이 원칙은 전력망뿐 아니라 도시 에너지 관리, 스마트시티 운영, 에이전틱 메쉬 플랫폼, AI 기반 제어 시스템 전반에 적용할 수 있다.

---

# MeshBoard 적용 고도화 설계

> 이 장부터는 위 논문 내용을 현재 `meshboard` 코드베이스에 접목하기 위한 구체 설계다.  
> 기준 시스템은 `FastAPI + PostgreSQL + LangGraph agent_runtime + MCP tool_catalog + React Workspace Board + CityLearn phase_all dataset`이다.

## 21. 현재 MeshBoard 시스템과 Grid-Agent 대응 관계

현재 MeshBoard는 이미 Grid-Agent를 붙일 수 있는 핵심 뼈대를 갖고 있다.

| MeshBoard 구성 | 현재 파일 | Grid-Agent 대응 |
| --- | --- | --- |
| Agent Registry | `backend/app/models/agent.py`, `backend/app/api/v1/agents.py` | Planner/Summarizer/Building Agent 등록 |
| Agent Runtime | `backend/app/services/agent_runtime.py` | LLM Planner 실행 루프 |
| Tool Catalog | `backend/app/services/tool_catalog.py` | Topology/Executor/Validator 도구 |
| Workspace Graph | `backend/app/models/workspace.py` | Agent-Mesh topology와 구독 관계 |
| CityLearn Board API | `backend/app/api/v1/citylearn.py` | simulation state feed |
| CityLearn Board Service | `backend/app/services/citylearn_board.py` | 현재 상태/빌딩별 상태 요약 |
| SACRBC Bridge | `backend/app/services/citylearn_sacrbc_inference.py` | baseline runner |
| Workspace Board UI | `frontend/src/pages/WorkspacePage.tsx` | topology, board, reasoning trace 표시 |
| Frontend CityLearn Client | `frontend/src/api/citylearn.ts` | board snapshot API contract |

핵심 결론:

- Grid-Agent의 `TopologyAgent`와 `ValidatorAgent`는 LLM보다 결정적 Python service로 구현한다.
- `PlannerAgent`와 `SummarizerAgent`는 기존 `agent_runtime.py`의 JSON 프로토콜을 사용한다.
- `ExecutorAgent`는 live 제어가 아니라 CityLearn sandbox step 또는 preview action evaluation으로 제한한다.
- Workspace의 `agent_building_mapping` metadata를 Agent-Mesh의 topology input으로 사용한다.
- Board는 "실제 제어 적용"이 아니라 "제안 -> sandbox 검증 -> 승인 후보 표시"를 먼저 제공한다.

---

## 22. MeshBoard용 목표 재정의

논문의 전력망 violation은 MeshBoard의 CityLearn `phase_all` 데이터셋에서는 다음처럼 치환한다.

| Grid-Agent violation | MeshBoard CityLearn violation |
| --- | --- |
| voltage violation | SOC 하한/상한 위험, 피크 시간 방전 여력 부족 |
| thermal overload | district net load peak 초과, ramping 초과 |
| disconnected bus | 빌딩 agent 미할당, action 누락, invalid action |
| disruptive action | 과도한 배터리 방전, 특정 빌딩 반복 부담 |
| power flow non-convergence | CityLearn env step 실패, schema/action mismatch |

MeshBoard의 1차 운영 목표는 다음 순서다.

1. `electrical_storage` action 범위와 SOC 제약을 위반하지 않는다.
2. district peak와 ramping을 줄인다.
3. 가격과 탄소가 높은 시간대 grid import를 줄인다.
4. 특정 빌딩만 반복적으로 희생하지 않도록 fairness를 유지한다.
5. 모든 action은 설명 가능한 JSON trace로 남긴다.

현재 `citylearn_challenge_2022_phase_all`의 active action은 `electrical_storage` 하나이므로 MVP action space는 배터리 충방전으로 제한한다.

---

## 23. 권장 아키텍처

### 23.1 런타임 구조

```text
React Workspace Board
  ├─ GET /api/v1/citylearn/board
  ├─ POST /api/v1/citylearn/grid-agent/plan
  └─ POST /api/v1/citylearn/grid-agent/commit-preview

FastAPI
  ├─ citylearn_board.py
  │    └─ CSV/SACRBC baseline snapshot
  ├─ citylearn_grid_agent.py
  │    ├─ TopologyAnalyzer
  │    ├─ MeshPlannerClient
  │    ├─ SandboxExecutor
  │    ├─ ConstraintValidator
  │    └─ ResolutionSummarizer
  ├─ agent_runtime.py
  │    └─ LLM JSON protocol
  └─ tool_catalog.py
       ├─ get_citylearn_state
       ├─ propose_battery_dispatch
       ├─ validate_citylearn_actions
       └─ summarize_citylearn_plan

Storage
  ├─ workspace.metadata.agent_building_mapping
  ├─ optional: citylearn_action_runs
  └─ optional: citylearn_action_steps
```

### 23.2 Agent-Mesh workflow

```text
1. Board requests current step.
2. TopologyAnalyzer builds district state from CityLearn snapshot + workspace mapping.
3. ViolationDetector finds peak/ramp/SOC/fairness issues.
4. PlannerAgent generates structured action candidates.
5. SandboxExecutor applies candidates to copied state only.
6. Validator scores before/after and rejects unsafe actions.
7. If rejected, feedback is appended and PlannerAgent retries.
8. SummarizerAgent creates operator-facing Korean explanation.
9. Board renders actions, score delta, validation result, and reasoning trace.
```

MVP에서는 CityLearn live env step이 아직 완전히 연결되어 있지 않으므로 `SandboxExecutor`는 `citylearn_board.py`와 같은 deterministic preview 계산으로 시작한다. 이후 `citylearn_sacrbc_inference.py`처럼 실제 env bridge가 안정화되면 같은 interface 뒤에 교체한다.

---

## 24. 데이터 모델 설계

### 24.1 Pydantic schema 초안

파일 후보: `backend/app/schemas/citylearn_grid_agent.py`

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


BatteryMode = Literal["charge", "discharge", "hold"]
ViolationType = Literal["peak", "ramping", "soc", "fairness", "mapping", "invalid_action"]


class CityLearnViolation(BaseModel):
    type: ViolationType
    target_id: str
    severity: float = Field(ge=0)
    current_value: float | None = None
    limit_value: float | None = None
    description: str


class CityLearnAction(BaseModel):
    building_id: str
    action: float = Field(ge=-1.0, le=1.0)
    mode: BatteryMode
    reason: str
    expected_effect: str
    confidence: float = Field(ge=0.0, le=1.0)


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

### 24.2 API request/response 초안

```python
class GridAgentPlanRequest(BaseModel):
    workspace_id: str
    step: int = Field(ge=0, le=8759)
    baseline_model: str = "sacrbc"
    agent_mesh_mode: str = "configured_agents"
    window: int = Field(default=72, ge=1, le=168)
    max_iterations: int = Field(default=3, ge=1, le=6)
    require_human_approval: bool = True


class GridAgentPlanResponse(BaseModel):
    run_id: str
    step: int
    topology_summary: dict
    initial_violations: list[CityLearnViolation]
    final_plan: CityLearnPlan | None
    validation: CityLearnValidationResult
    iterations: list[dict]
    operator_summary: str
```

---

## 25. Backend service 구조

파일 후보: `backend/app/services/citylearn_grid_agent.py`

```python
from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.citylearn_board import get_board_snapshot


@dataclass
class GridAgentRunConfig:
    workspace_id: str
    step: int
    baseline_model: str
    agent_mesh_mode: str
    window: int = 72
    max_iterations: int = 3


class TopologyAnalyzer:
    def analyze(self, snapshot: dict[str, Any], workspace_metadata: dict[str, Any]) -> dict[str, Any]:
        mapping = workspace_metadata.get("agent_building_mapping", {})
        buildings = snapshot["buildings"]
        district_load = sum(item["agent_mesh_net_load_kwh"] for item in buildings)
        baseline_load = sum(item["baseline_net_load_kwh"] for item in buildings)

        return {
            "dataset": snapshot["dataset"],
            "runtime": snapshot["runtime"],
            "step": snapshot["step"],
            "district": {
                "baseline_load_kwh": round(baseline_load, 3),
                "agent_mesh_load_kwh": round(district_load, 3),
                "delta_kwh": round(baseline_load - district_load, 3),
            },
            "buildings": buildings,
            "mapping": mapping,
            "controllable_assets": [
                {
                    "building_id": item["building_id"],
                    "asset": "electrical_storage",
                    "action_min": -1.0,
                    "action_max": 1.0,
                    "soc": item["battery_soc"],
                    "pv_generation_kwh": item["pv_generation_kwh"],
                    "net_load_kwh": item["agent_mesh_net_load_kwh"],
                }
                for item in buildings
            ],
        }


class ViolationDetector:
    def detect(self, topology: dict[str, Any]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        buildings = topology["buildings"]
        district_load = topology["district"]["agent_mesh_load_kwh"]

        if district_load >= 55.0:
            violations.append({
                "type": "peak",
                "target_id": "district",
                "severity": min(1.0, (district_load - 55.0) / 20.0),
                "current_value": district_load,
                "limit_value": 55.0,
                "description": "District net load exceeds the peak management threshold.",
            })

        for item in buildings:
            if item["battery_soc"] <= 0.18 and item["battery_action"] == "discharging":
                violations.append({
                    "type": "soc",
                    "target_id": item["building_id"],
                    "severity": 0.8,
                    "current_value": item["battery_soc"],
                    "limit_value": 0.18,
                    "description": "Battery is near lower SOC bound while discharging.",
                })

        mapped = {
            item["building_id"]
            for item in topology.get("mapping", {}).get("buildings", [])
            if item.get("assigned_agent_id")
        }
        for item in buildings:
            if item["building_id"] not in mapped:
                violations.append({
                    "type": "mapping",
                    "target_id": item["building_id"],
                    "severity": 0.35,
                    "description": "No building agent is assigned in workspace mapping.",
                })

        return violations


class SandboxExecutor:
    def execute(self, topology: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        sandbox = copy.deepcopy(topology)
        by_building = {item["building_id"]: item for item in sandbox["buildings"]}

        for action in actions:
            building = by_building.get(action["building_id"])
            if not building:
                continue
            clipped = max(-1.0, min(1.0, float(action["action"])))
            soc = float(building["battery_soc"])
            net_load = float(building["agent_mesh_net_load_kwh"])

            if clipped < 0:
                discharge_kwh = min(abs(clipped) * 5.0, max(0.0, (soc - 0.15) * 6.4))
                building["agent_mesh_net_load_kwh"] = round(max(0.0, net_load - discharge_kwh), 3)
                building["battery_soc"] = round(max(0.15, soc - discharge_kwh / 6.4), 3)
                building["battery_action"] = "discharging"
            elif clipped > 0:
                charge_kwh = min(clipped * 5.0, max(0.0, (0.95 - soc) * 6.4))
                building["agent_mesh_net_load_kwh"] = round(net_load + charge_kwh, 3)
                building["battery_soc"] = round(min(0.95, soc + charge_kwh * 0.9 / 6.4), 3)
                building["battery_action"] = "charging"
            else:
                building["battery_action"] = "idle"

        sandbox["district"]["agent_mesh_load_kwh"] = round(
            sum(item["agent_mesh_net_load_kwh"] for item in sandbox["buildings"]),
            3,
        )
        return sandbox


class ConstraintValidator:
    def score(self, topology: dict[str, Any]) -> float:
        district_load = topology["district"]["agent_mesh_load_kwh"]
        soc_penalty = sum(
            10.0 for item in topology["buildings"]
            if item["battery_soc"] < 0.15 or item["battery_soc"] > 0.95
        )
        peak_penalty = max(0.0, district_load - 55.0) * 2.0
        return district_load + soc_penalty + peak_penalty

    def validate(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        detector: ViolationDetector,
        clipped_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        before_violations = detector.detect(before)
        after_violations = detector.detect(after)
        score_before = self.score(before)
        score_after = self.score(after)
        approved = score_after < score_before and not any(
            item["type"] in {"soc", "invalid_action"} and item["severity"] >= 0.8
            for item in after_violations
        )

        return {
            "approved": approved,
            "score_before": round(score_before, 3),
            "score_after": round(score_after, 3),
            "resolved_violations": [
                item for item in before_violations
                if item["target_id"] not in {v["target_id"] for v in after_violations}
            ],
            "remaining_violations": after_violations,
            "new_violations": [
                item for item in after_violations
                if item["target_id"] not in {v["target_id"] for v in before_violations}
            ],
            "clipped_actions": clipped_actions,
            "feedback": "Approved sandbox plan." if approved else "Plan did not improve score enough or introduced unsafe state.",
        }
```

이 코드는 production-ready 구현이 아니라 interface와 책임 분리를 보여주는 초안이다. 실제 구현 시에는 Pydantic schema를 사용해 action을 검증하고, magic number인 `55.0`, `5.0`, `6.4`는 dataset schema에서 읽어야 한다.

---

## 26. API endpoint 설계

파일 후보: `backend/app/api/v1/citylearn.py`에 추가하거나 `citylearn_grid_agent.py` router를 분리한다.

```python
@router.post("/grid-agent/plan")
async def citylearn_grid_agent_plan(
    payload: GridAgentPlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = await load_workspace_for_user(db, payload.workspace_id, current_user.user_id)
    snapshot = get_board_snapshot(
        step=payload.step,
        baseline_model=payload.baseline_model,
        agent_mesh_mode=payload.agent_mesh_mode,
        window=payload.window,
    )
    result = await run_citylearn_grid_agent(
        snapshot=snapshot,
        workspace_metadata=workspace.metadata_ or {},
        config=payload,
    )
    return result
```

초기 endpoint는 실제 DB commit을 하지 않는 것이 좋다. 이름도 `plan`, `preview`, `validate`처럼 비파괴 동작임을 명확히 한다.

권장 endpoint:

| Method | Path | 역할 |
| --- | --- | --- |
| `GET` | `/citylearn/board` | 기존 board snapshot |
| `POST` | `/citylearn/grid-agent/analyze` | topology + violations 반환 |
| `POST` | `/citylearn/grid-agent/plan` | planner + sandbox validation 실행 |
| `POST` | `/citylearn/grid-agent/commit-preview` | 승인된 plan을 UI trace로 저장 |

---

## 27. MCP tool 확장 설계

기존 `agent_runtime.py`는 LLM이 tool ID를 JSON으로 호출하는 구조다. Grid-Agent용 도구는 `tool_catalog.py`에 추가할 수 있다.

### 27.1 Tool 목록

| Tool ID | 결정성 | 역할 |
| --- | --- | --- |
| `get_citylearn_board_state` | deterministic | 현재 step의 snapshot 조회 |
| `detect_citylearn_violations` | deterministic | peak/SOC/mapping violation 탐지 |
| `validate_citylearn_battery_plan` | deterministic | action list sandbox 검증 |
| `summarize_citylearn_validation` | deterministic or LLM | operator summary 재료 생성 |

### 27.2 Tool 구현 예시

```python
@lc_tool
def validate_citylearn_battery_plan(step: int, actions_json: str, baseline_model: str = "sacrbc") -> str:
    """CityLearn battery action plan을 sandbox에서 검증하고 JSON 문자열로 반환합니다.

    Args:
        step: CityLearn time step, 0~8759.
        actions_json: [{"building_id":"Building_1","action":-0.3,"reason":"..."}] 형태 JSON.
        baseline_model: 비교 baseline.
    """
    try:
        actions = json.loads(actions_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"approved": False, "feedback": f"Invalid JSON: {exc}"}, ensure_ascii=False)

    snapshot = get_board_snapshot(
        step=step,
        baseline_model=baseline_model,
        agent_mesh_mode="configured_agents",
        window=72,
    )
    topology = TopologyAnalyzer().analyze(snapshot, workspace_metadata={})
    detector = ViolationDetector()
    after = SandboxExecutor().execute(topology, actions)
    result = ConstraintValidator().validate(topology, after, detector, actions)
    return json.dumps(result, ensure_ascii=False)
```

주의:

- LLM에게 raw `get_board_snapshot` 전체를 반복 제공하면 token이 커진다.
- Tool 출력은 Planner가 재계획할 수 있도록 `approved`, `score_before`, `score_after`, `feedback`, `remaining_violations` 중심으로 줄인다.
- `actions_json` 문자열 방식은 LangChain tool schema 충돌을 줄이는 단순 MVP다. 이후 Pydantic args schema로 바꿀 수 있다.

---

## 28. Agent Card 설계

MeshBoard Creator에서 다음 에이전트를 등록하면 Workspace에 바로 붙일 수 있다.

### 28.1 City Grid Coordinator

```json
{
  "name": "City Grid Coordinator",
  "version": "0.1.0",
  "purpose": "CityLearn district-level peak, ramping, cost, carbon objective를 계산하고 building agents에 운영 목표를 배포한다.",
  "roles": ["energy", "coordinator", "citylearn"],
  "tools": [
    "get_citylearn_board_state",
    "detect_citylearn_violations",
    "validate_citylearn_battery_plan"
  ],
  "agent_card": {
    "system_prompt": "당신은 MeshBoard의 CityLearn district 운영 coordinator입니다. 모든 답변은 agent_runtime의 JSON 프로토콜을 따라야 합니다. 배터리 action은 -1.0부터 1.0 사이이며, 음수는 discharge, 양수는 charge입니다. 먼저 district peak/ramping/SOC/mapping violation을 확인하고, load curtailment나 임의 설비 제어는 제안하지 마십시오. 제안은 반드시 validate_citylearn_battery_plan 도구로 검증한 뒤 final로 요약하십시오."
  }
}
```

### 28.2 Building Battery Agent

```json
{
  "name": "Building Battery Agent",
  "version": "0.1.0",
  "purpose": "할당된 CityLearn building의 battery SOC, PV, net load를 보고 local battery action을 제안한다.",
  "roles": ["energy", "building-agent", "battery"],
  "tools": ["get_citylearn_board_state"],
  "agent_card": {
    "system_prompt": "당신은 하나의 CityLearn building battery agent입니다. 할당된 building_id 외의 자산을 제어하지 마십시오. action은 electrical_storage 하나이며 -1.0~1.0 범위입니다. SOC가 0.2 미만이면 방전을 피하고, 0.9 초과이면 충전을 피하십시오. 출력은 coordinator가 병합할 수 있는 JSON decision으로 작성하십시오."
  }
}
```

### 28.3 Constraint Guard

```json
{
  "name": "CityLearn Constraint Guard",
  "version": "0.1.0",
  "purpose": "Agent-Mesh가 제안한 battery action을 sandbox에서 검증하고 clipping/rollback 여부를 결정한다.",
  "roles": ["energy", "validator", "safety"],
  "tools": ["validate_citylearn_battery_plan"],
  "agent_card": {
    "system_prompt": "당신은 안전 검증 agent입니다. 검증되지 않은 action을 승인하지 마십시오. score_after가 score_before보다 낮고 SOC 또는 invalid_action violation이 없을 때만 승인하십시오. 실패 시 재계획에 필요한 짧은 feedback을 JSON final로 반환하십시오."
  }
}
```

---

## 29. Planner prompt 고도화

`agent_runtime.py`의 시스템 프롬프트는 agent card 뒤에 MCP manifest와 JSON protocol을 붙인다. 따라서 Planner의 custom prompt는 아래처럼 "도메인 정책"과 "내부 출력 형식"에 집중한다.

```text
당신은 MeshBoard CityLearn Grid-Agent의 Planner입니다.

목표:
- CityLearn phase_all 17개 building의 electrical_storage action만 사용한다.
- district peak와 ramping을 줄이고, SOC 안전 범위를 지킨다.
- action 수와 과도한 discharge를 최소화한다.

운영 제약:
- action 범위는 [-1.0, 1.0]이다.
- action < 0: battery discharge, net load 감소.
- action > 0: battery charge, net load 증가 가능.
- SOC < 0.20인 building에는 discharge를 제안하지 않는다.
- SOC > 0.90인 building에는 charge를 제안하지 않는다.
- 존재하지 않는 building_id를 만들지 않는다.
- EV, washing machine, HVAC action은 현재 dataset에서 비활성이다.
- load curtailment는 현재 MVP action space에 없다.

계획 우선순위:
1. 높은 net load와 충분한 SOC를 가진 building의 discharge.
2. PV surplus 시간대에는 SOC 낮은 building의 charge.
3. 특정 building에 action이 집중되면 action 크기를 분산.
4. 검증 실패 action sequence는 반복하지 않는다.

도구 사용:
- 현재 상태가 필요하면 get_citylearn_board_state를 호출한다.
- action plan은 validate_citylearn_battery_plan으로 검증한다.
- 검증 승인 전에는 final 승인 답변을 하지 않는다.

내부 action 후보 형식:
[
  {
    "building_id": "Building_1",
    "action": -0.35,
    "mode": "discharge",
    "reason": "SOC is sufficient and current net load is high.",
    "expected_effect": "Reduce district peak by about 1.7 kWh.",
    "confidence": 0.78
  }
]
```

`agent_runtime.py`가 요구하는 최종 출력은 다음 둘 중 하나여야 한다.

```json
{"action":"tool","tool":"validate_citylearn_battery_plan","arguments":{"step":4210,"actions_json":"[{\"building_id\":\"Building_1\",\"action\":-0.35,\"reason\":\"...\"}]","baseline_model":"sacrbc"}}
```

```json
{"action":"final","answer":"검증 결과 승인 가능한 plan입니다. Building 1과 Building 10을 방전해 district peak를 낮추며 SOC 하한 violation은 없습니다."}
```

---

## 30. Validator feedback prompt

Planner 재시도 시에는 자연어 힌트보다 구조화 feedback이 낫다.

```json
{
  "previous_plan_failed": true,
  "reason": "Plan introduced SOC violation for Building_3.",
  "score_before": 61.4,
  "score_after": 62.8,
  "remaining_violations": [
    {
      "type": "soc",
      "target_id": "Building_3",
      "severity": 0.8
    }
  ],
  "retry_policy": [
    "Do not discharge Building_3.",
    "Prefer buildings with SOC >= 0.45.",
    "Keep total number of actions <= 5."
  ],
  "forbidden_action_keys": [
    "Building_3:-0.4"
  ]
}
```

이 feedback을 Planner prompt에 붙일 때는 다음 문장을 추가한다.

```text
The previous plan failed validation. You must not repeat any forbidden_action_keys. Generate a revised plan and validate it again.
```

---

## 31. Workspace metadata 활용

`WorkspacePage.tsx`는 이미 `agent_building_mapping`을 workspace metadata에 넣는다. Grid-Agent는 이 값을 topology로 사용한다.

예상 구조:

```json
{
  "environment_template_id": "citylearn-2022",
  "assignment_mode": "building_or_central",
  "central_controller_agents": [
    {
      "agent_id": "uuid",
      "agent_name": "City Grid Coordinator"
    }
  ],
  "buildings": [
    {
      "building_id": "Building_1",
      "assigned_agent_id": "uuid",
      "assigned_agent_name": "Building Battery Agent",
      "metadata": {
        "battery_capacity": 6.4,
        "pv_power": 5.0,
        "pv_nominal_power": 5.0
      }
    }
  ]
}
```

활용 방식:

- `central_controller_agents`가 없으면 Board는 `configured_agents` 대신 `demo_heuristic`을 권장한다.
- `assigned_agent_id`가 없는 building은 `mapping` violation으로 표시한다.
- 하나의 agent가 여러 building에 할당된 경우 UI에서는 building별 virtual node로 분리 표시한다.
- Validator는 미할당 building에도 fallback heuristic action을 낼 수 있지만, 그 action은 `confidence`를 낮게 표시한다.

---

## 32. Frontend 반영 설계

현재 Board에는 `baseline`, `agent_mesh`, building heatmap, selected building detail이 있다. 여기에 Grid-Agent 결과를 다음 위치에 붙인다.

### 32.1 추가 상태

파일 후보: `frontend/src/api/citylearn.ts`

```ts
export interface CityLearnGridAgentAction {
  building_id: string;
  action: number;
  mode: 'charge' | 'discharge' | 'hold';
  reason: string;
  expected_effect: string;
  confidence: number;
}

export interface CityLearnGridAgentViolation {
  type: 'peak' | 'ramping' | 'soc' | 'fairness' | 'mapping' | 'invalid_action';
  target_id: string;
  severity: number;
  current_value?: number | null;
  limit_value?: number | null;
  description: string;
}

export interface CityLearnGridAgentPlanResponse {
  run_id: string;
  step: number;
  initial_violations: CityLearnGridAgentViolation[];
  final_plan: {
    strategy_summary: string;
    actions: CityLearnGridAgentAction[];
    risk_assessment: string;
  } | null;
  validation: {
    approved: boolean;
    score_before: number;
    score_after: number;
    feedback: string;
    remaining_violations: CityLearnGridAgentViolation[];
  };
  iterations: Array<Record<string, unknown>>;
  operator_summary: string;
}
```

### 32.2 API client

```ts
runGridAgentPlan: async (payload: {
  workspace_id: string;
  step: number;
  baseline_model: CityLearnBaselineModel;
  agent_mesh_mode: CityLearnAgentMeshMode;
  window?: number;
  max_iterations?: number;
}): Promise<CityLearnGridAgentPlanResponse> => {
  const res = await client.post<CityLearnGridAgentPlanResponse>('/citylearn/grid-agent/plan', payload);
  return res.data;
}
```

### 32.3 UI 배치

Board 우측 또는 하단 inspector에 다음을 추가한다.

- `Run Grid-Agent Plan` 버튼
- `Validation approved/rejected` badge
- `Score before -> after`
- `Initial violations`
- `Proposed actions`
- `Operator summary`
- `Iteration trace`

빌딩 카드에는 다음 표시를 추가한다.

- proposed action 값
- charge/discharge/hold mode
- confidence
- action reason tooltip
- validation rejected 시 붉은 outline

---

## 33. 저장 설계

초기에는 DB migration 없이 response만 UI에 표시해도 된다. 실험/논문용 로그가 필요하면 아래 테이블을 추가한다.

### 33.1 `citylearn_grid_agent_runs`

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `run_id` | UUID PK | 실행 ID |
| `workspace_id` | UUID FK | workspace |
| `step` | integer | CityLearn timestep |
| `baseline_model` | text | 비교 baseline |
| `agent_mesh_mode` | text | 실행 모드 |
| `approved` | boolean | 최종 승인 여부 |
| `score_before` | numeric | 검증 전 score |
| `score_after` | numeric | 검증 후 score |
| `operator_summary` | text | 최종 요약 |
| `payload` | JSONB | 전체 trace |
| `created_at` | timestamptz | 생성 시각 |

### 33.2 `citylearn_grid_agent_actions`

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `action_id` | UUID PK | action ID |
| `run_id` | UUID FK | run |
| `building_id` | text | building |
| `action_value` | numeric | -1~1 |
| `mode` | text | charge/discharge/hold |
| `reason` | text | Planner reason |
| `expected_effect` | text | 예상 효과 |
| `confidence` | numeric | 0~1 |

이 로그가 쌓이면 success rate, action efficiency, repeated burden fairness를 계산할 수 있다.

---

## 34. 평가 지표를 MeshBoard KPI로 변환

| 논문 지표 | MeshBoard 지표 | 계산 |
| --- | --- | --- |
| Success Rate | 승인된 plan 비율 | `approved_runs / total_runs` |
| Action Efficiency | kWh 절감/action | `(score_before - score_after) / action_count` |
| Convergence Speed | 평균 iteration | `avg(len(iterations))` |
| Runtime | API latency | request start/end |
| Solution Quality | 복합 점수 개선 | peak/ramp/SOC/fairness weighted score |
| New Violation Rate | 새 violation 발생률 | `new_violations > 0` 비율 |

추천 dashboard metric:

```text
grid_agent_improvement = score_before - score_after
peak_reduction_kwh = district_peak_before - district_peak_after
action_efficiency = peak_reduction_kwh / max(1, action_count)
soc_risk_count = count(building.soc < 0.2 or building.soc > 0.9)
fairness_burden = stddev(abs(action_value) by building over last N runs)
```

---

## 35. 구현 로드맵

### Phase A. 문서/스키마 정렬

- [ ] `docs/Grid_Agent.md`의 MeshBoard 적용 설계를 기준 문서로 채택
- [ ] `citylearn_grid_agent.py` schema 초안 추가
- [ ] threshold와 scoring 정책을 상수 파일로 분리

### Phase B. Deterministic Grid-Agent MVP

- [ ] `TopologyAnalyzer` 구현
- [ ] `ViolationDetector` 구현
- [ ] `SandboxExecutor` 구현
- [ ] `ConstraintValidator` 구현
- [ ] LLM 없이 heuristic Planner로 `/grid-agent/analyze`와 `/grid-agent/plan` 제공

### Phase C. LLM Planner 연결

- [ ] `tool_catalog.py`에 CityLearn 검증 tool 추가
- [ ] Creator seed agent로 `City Grid Coordinator`, `Constraint Guard` 추가
- [ ] `agent_runtime.py` invoke 결과를 Grid-Agent orchestration에서 호출
- [ ] Planner 실패 시 validation feedback 재주입

### Phase D. Board UI 통합

- [ ] `frontend/src/api/citylearn.ts`에 Grid-Agent 타입과 API 추가
- [ ] Board에 `Run Grid-Agent Plan` 버튼 추가
- [ ] validation result panel 추가
- [ ] building heatmap에 proposed action overlay 추가

### Phase E. 실험 로그

- [ ] run/action table migration 추가
- [ ] approved/rejected trace 저장
- [ ] KPI dashboard 확장
- [ ] BasicRBC/SACRBC/Agent-Mesh/Grid-Agent 비교 리포트 생성

---

## 36. 가장 먼저 구현할 최소 단위

가장 작은 유효 구현은 다음이다.

```text
POST /api/v1/citylearn/grid-agent/plan
  input: workspace_id, step, baseline_model, agent_mesh_mode
  output:
    - current topology summary
    - violations
    - deterministic battery action plan
    - sandbox validation score before/after
    - Korean operator summary
```

이 단계에서는 LLM 호출 없이도 Grid-Agent 논문의 핵심인 `analyze -> plan -> execute in sandbox -> validate -> summarize` 흐름을 보여줄 수 있다. 이후 Planner만 LLM으로 교체하면 논문형 시스템이 된다.

---

## 37. MeshBoard 적용 원칙

1. LLM은 action을 제안하지만, action 적용 여부는 Validator가 결정한다.
2. CityLearn `phase_all`에서는 `electrical_storage` 외 action을 만들지 않는다.
3. Workspace mapping이 topology의 source of truth다.
4. Board는 preview와 live runner 연결 상태를 명확히 분리해서 표시한다.
5. 실패 trace도 저장한다. 실패는 재계획 품질을 높이는 데이터다.
6. Human approval을 기본값으로 두고, 자동 적용은 별도 phase에서만 연다.

최종적으로 MeshBoard의 Grid-Agent는 "LLM이 전력망을 직접 제어하는 시스템"이 아니라, **에이전트 메쉬가 제안한 도시 에너지 제어 전략을 시뮬레이션으로 검증하고 운영자가 승인할 수 있게 만드는 설명 가능한 제어 보조 시스템**으로 정의하는 것이 가장 타당하다.

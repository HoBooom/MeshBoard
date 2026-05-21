# CityLearn 데이터셋 및 기존 에이전트 시스템 분석

## 1. 분석 범위

이 문서는 MeshBoard의 CityLearn 기반 도시 전력 관리 데모를 새로운 agentic 구조로 재구성하기 위한 기준 문서다.

주 분석 대상은 현재 Board와 `best_inference_bundle.pt`가 기준으로 삼는 17개 빌딩 `phase_all` 데이터셋이다.

- 데이터셋: `CityLearn_old_system/data/datasets/citylearn_challenge_2022_phase_all`
- 기존 시뮬레이션/환경 코드: `CityLearn_old_system/citylearn`
- 현재 확인된 학습 artifact: `CityLearn_old_system/citylearn/best_inference_bundle.pt`
- artifact 모델: `citylearn.agents.sac.SACRBC`
- artifact reward: `citylearn.reward_function.MARLAndSolarPenaltyReward`
- episode 길이: 8760 time steps
- time step 간격: 3600초, 즉 1시간
- 제어 구조: `central_agent=false`, 즉 빌딩별 decentralized agent 구조

주의할 점: `citylearn_challenge_2022_phase_all`에는 EV charger와 washing machine 제어가 활성화되어 있지 않다. EV/washing-machine action은 `citylearn_challenge_2022_phase_all_plus_evs` 또는 `citylearn_three_phase_electrical_service_demo` 계열에서 다뤄진다. 현재 Board는 학습 완료 artifact와 맞추기 위해 `phase_all` 기준으로 재구성한다.

## 2. 데이터셋 구조

### 2.1 공통 시간축

`citylearn_challenge_2022_phase_all`은 1년치 시간 단위 시뮬레이션 데이터다.

| 항목 | 값 |
| --- | --- |
| 시작 step | 0 |
| 종료 step | 8759 |
| 총 step | 8760 |
| step 간격 | 1 hour |
| 빌딩 수 | 17 |
| 기본 제어 방식 | decentralized |

각 time step에서 환경은 다음 흐름으로 동작한다.

1. agent가 각 빌딩의 관측값을 받는다.
2. agent가 각 빌딩의 `electrical_storage` action을 낸다.
3. environment가 배터리 충방전 결과를 반영한다.
4. 빌딩별 `net_electricity_consumption`을 계산한다.
5. cost, carbon, reward, KPI가 갱신된다.

### 2.2 주요 입력 파일

| 파일 | 역할 |
| --- | --- |
| `schema.json` | 시뮬레이션 구성, active observation/action, agent, reward, 빌딩 설비 정의 |
| `Building_1.csv` ~ `Building_17.csv` | 빌딩별 부하, 태양광 발전, 냉난방/급탕 수요 등 |
| `weather.csv` | 외기 온도, 습도, 일사량 및 1~3 step forecast |
| `pricing.csv` | 전력 가격 및 1~3 step forecast |
| `carbon_intensity.csv` | grid carbon intensity |

### 2.3 활성 관측값

현재 2022 phase all 데이터셋에서 agent가 사용할 수 있는 핵심 관측값은 다음과 같다.

| 범주 | 관측값 |
| --- | --- |
| 시간 | `month`, `day_type`, `hour` |
| 날씨 | `outdoor_dry_bulb_temperature`, `outdoor_relative_humidity`, `diffuse_solar_irradiance`, `direct_solar_irradiance` |
| 예측 | 온도/습도/일사량의 `predicted_1`, `predicted_2`, `predicted_3` |
| grid | `carbon_intensity`, `electricity_pricing`, 가격 forecast |
| 빌딩 | `non_shiftable_load`, `solar_generation`, `electrical_storage_soc`, `net_electricity_consumption` |

의미상 나누면 다음과 같다.

- 시간/날씨/가격/탄소는 도시 전체에 공유 가능한 외생 상태다.
- `non_shiftable_load`, `solar_generation`, `electrical_storage_soc`, `net_electricity_consumption`은 빌딩별 상태다.
- forecast는 agent가 단기 계획을 세우기 위한 최소 예측 정보다.

### 2.4 활성 action

현재 Board 기준 활성 action은 하나다.

| action | 범위 | 의미 |
| --- | --- | --- |
| `electrical_storage` | 대체로 `[-1, 1]` | 배터리 충방전 명령 |

코드 기준으로 `electrical_storage` action은 배터리 nominal power에 곱해져 kW로 변환되고, 1시간 step에서는 kWh 단위 에너지로 반영된다.

- 양수 action: 배터리 충전
- 음수 action: 배터리 방전
- 제약: 배터리 capacity, nominal power, SOC 경계, 효율, degradation 계수

### 2.5 빌딩 설비 요약

17개 빌딩은 모두 electrical storage를 가진다.

| 항목 | 값 |
| --- | --- |
| 배터리 capacity | 6.4 kWh |
| 배터리 nominal power | 5.0 kW |
| 배터리 효율 | 0.9 |
| 활성 제어 대상 | electrical storage |

PV nominal power는 빌딩별로 4.0 또는 5.0 kW로 정의되어 있다. 실제 `Building_*.csv`의 `solar_generation` 값은 스키마 설비 정의와 결합되어 환경 내부에서 net consumption 계산에 반영된다.

## 3. 기존 CityLearn 시스템의 목표

### 3.1 기본 reward

기본 reward는 현재 step의 grid import를 줄이는 방향이다.

```text
reward = -max(net_electricity_consumption, 0) ** exponent
```

즉, grid에서 전력을 많이 가져올수록 reward가 더 나빠진다. export, 즉 음수 net consumption은 기본 reward에서 직접 보상하지 않는다. central agent 모드에서는 전체 빌딩 reward를 합산하고, decentralized 모드에서는 빌딩별 reward를 따로 반환한다.

이 구조의 의미는 명확하다.

- agent는 grid import를 줄여야 한다.
- 배터리를 피크 시간에 방전하면 reward가 개선된다.
- PV surplus를 언제 저장할지 직접 reward로 강하게 장려하지는 않는다.
- 가격/탄소 forecast가 관측값에 있어도 기본 reward는 비용/탄소를 직접 최적화하지 않는다.

### 3.2 KPI와 평가 기준

CityLearn은 reward와 별개로 여러 cost function/KPI를 제공한다.

| KPI | 의미 | 관리 관점 |
| --- | --- | --- |
| `electricity_consumption` | grid import 누적량 | 총 전력 수요 절감 |
| `zero_net_energy` | net consumption 누적합 | 연간 net-zero 성능 |
| `carbon_emissions` | carbon intensity 반영 배출량 | 저탄소 운전 |
| `cost` | pricing 반영 전력비 | 비용 절감 |
| `peak` | 구간별 최대 수요 | 피크 억제 |
| `ramping` | step 간 수요 변화량 | grid 안정성 |
| `one_minus_load_factor` | 평균 대비 피크가 큰 정도 | 부하 평탄화 |
| `discomfort` | 온열 comfort 위반 | 수요반응의 사용자 영향 |

현재 2022 phase all plus EVs 구성에서는 comfort 관련 active observation/action이 비활성에 가깝고, EV departure SOC와 washing-machine schedule 제약이 추가된다. 현실적인 1차 목표는 전력/피크/비용/탄소에 EV/세탁기 제약 위반 방지를 더한 형태다.

### 3.3 Rule-based Controller 목표

`BasicRBC`는 시간 기반 규칙으로 저장장치를 제어한다.

기본 패턴:

- 09:00~21:00: storage 방전, action 약 `-0.08`
- 22:00~08:00: storage 충전, action 약 `0.091`

의도:

- 낮/활동 시간대 grid import를 배터리 방전으로 줄인다.
- 야간에는 배터리를 충전해 다음 피크 구간에 대비한다.
- 가격/탄소/PV 예측을 정교하게 쓰기보다는 시간대 경험칙에 의존한다.

`OptimizedRBC`, `BasicBatteryRBC`는 이 규칙을 조금 더 세분화한다.

- `OptimizedRBC`: 07:00~22:00 사이 방전 강도를 구간별로 다르게 설정하고, 야간 충전.
- `BasicBatteryRBC`: 06:00~14:00 충전, 그 외 방전. 태양광 발전 활용에 더 가까운 정책.

### 3.4 RL/SAC 계열 목표

`SAC`는 Soft Actor-Critic 기반 강화학습 agent다.

구성 특징:

- 빌딩별 replay buffer 사용
- observation normalization 및 reward normalization
- policy network, twin Q-network, target Q-network 사용
- exploration 기간에는 랜덤 또는 RBC-guided action
- 이후 policy에서 action sampling

SAC가 직접 최적화하는 것은 reward다. 따라서 reward가 기본 `RewardFunction`이면 SAC도 결국 `net_electricity_consumption`을 줄이는 정책을 학습한다.

중요한 설계 포인트:

- RL은 “무엇을 reward로 주느냐”에 강하게 종속된다.
- 비용/탄소/피크까지 최적화하려면 reward를 composite하게 설계해야 한다.
- 관측값에는 가격/탄소 forecast가 이미 있으므로, reward만 잘 정의하면 학습 대상에 포함할 수 있다.

### 3.5 MARLISA 계열 목표

`MARLISA`는 SAC 기반에 정보 공유/상태 추정/coordination variable을 추가한 multi-agent 구조다.

핵심 의도:

- 개별 빌딩 agent가 완전히 고립되어 행동하지 않게 한다.
- 각 agent가 다른 빌딩의 행동/소비 영향까지 추정하도록 만든다.
- local action이 district-level net consumption에 미치는 영향을 coordination variable로 반영한다.

이는 새로운 agentic architecture에 특히 중요하다. 빌딩별 agent를 하나의 독립 agent로 표현하되, city-level coordinator가 grid 관점의 목표를 방송하고, 빌딩 agent가 지역 상태와 도시 상태를 함께 고려하도록 설계해야 한다.

## 4. 도시전력 관리 기준

새로운 agentic 구조는 기존 reward 하나만 보고 움직이면 안 된다. 도시 전력 관리 시스템으로 보려면 다음 우선순위가 필요하다.

### 4.1 운영 우선순위

1. **안전/제약 준수**
   - 배터리 SOC 0~100% 범위 준수
   - nominal power 초과 금지
   - 충방전 효율/열화 반영
   - 향후 EV가 들어오면 departure required SOC 위반 금지

2. **피크 억제**
   - 도시 전체 `net_electricity_consumption`의 최대값을 낮춘다.
   - 특히 17:00~21:00 또는 dataset상 고수요 시간대 방전을 우선한다.

3. **ramping 완화**
   - 시간 간 전력 수요 급변을 줄인다.
   - grid operator 관점에서는 단순 총량보다 ramping이 더 중요할 수 있다.

4. **총 grid import 절감**
   - 누적 positive net consumption을 줄인다.
   - PV surplus를 저장해 이후 수요 시간에 쓴다.

5. **전력 비용 절감**
   - `electricity_pricing`과 forecast를 사용해 비싼 시간대 grid import를 줄인다.

6. **탄소 배출 절감**
   - `carbon_intensity`가 높은 시간대 grid import를 줄인다.

7. **공정성**
   - 일부 빌딩만 이득을 보고 다른 빌딩이 계속 손해 보는 구조를 피한다.
   - 빌딩별 benefit, peak reduction, SOC 스트레스가 지나치게 편향되지 않아야 한다.

### 4.2 권장 composite objective

새 agentic 구조에서 city-level objective는 다음과 같이 잡는 것이 좋다.

```text
minimize:
  w1 * total_grid_import
+ w2 * district_peak
+ w3 * ramping
+ w4 * electricity_cost
+ w5 * carbon_emission
+ w6 * fairness_penalty
+ w7 * constraint_violation
```

초기 가중치 제안:

| 항목 | 권장 가중치 | 이유 |
| --- | ---: | --- |
| constraint_violation | 매우 높음 | 물리/운영 제약 위반 방지 |
| district_peak | 높음 | 도시전력 관리에서 핵심 |
| ramping | 중간~높음 | grid 안정성 |
| total_grid_import | 중간 | 기본 reward와 일치 |
| electricity_cost | 중간 | 가격 기반 수요반응 |
| carbon_emission | 중간 | 저탄소 운전 |
| fairness_penalty | 중간 | 빌딩 간 불균형 방지 |

### 4.3 실시간 의사결정 기준

각 time step에서 agentic system은 다음 질문에 답해야 한다.

1. 지금 district net load가 평소보다 높은가?
2. 다음 1~3시간 forecast에서 가격/탄소/수요 피크가 오는가?
3. 현재 PV surplus가 있는 빌딩은 어디인가?
4. SOC가 충분해 피크 방전에 기여할 수 있는 빌딩은 어디인가?
5. SOC가 낮아 미래 피크 대응을 위해 충전해야 하는 빌딩은 어디인가?
6. 특정 빌딩만 반복적으로 방전 부담을 지고 있지는 않은가?

## 5. 새로운 Agentic 구조 제안

### 5.1 노드 모델

현재 MeshBoard 요구사항처럼 빌딩에 할당된 agent는 각각 독립된 node로 표현하는 것이 맞다.

권장 노드:

| 노드 | 역할 |
| --- | --- |
| City Grid Coordinator | 도시 전체 KPI, 피크, 가격, 탄소 목표를 계산하고 지시 |
| Building Agent `Building_i` | 해당 빌딩의 SOC, 부하, PV, action 제안 |
| Forecast Agent | weather/pricing/carbon forecast 요약 |
| Constraint Guard Agent | action clipping, SOC/power 제약 검사 |
| Evaluator Agent | KPI 계산, baseline/RBC/agent-mesh 비교 |
| Event Agent | 돌발 수요 증가, PV 감소, outage 같은 이벤트 주입 |

### 5.2 빌딩 agent의 입력

각 Building Agent는 최소 다음 상태를 받아야 한다.

- local:
  - `non_shiftable_load`
  - `solar_generation`
  - `electrical_storage_soc`
  - `net_electricity_consumption`
  - battery capacity, nominal power, efficiency
- shared:
  - `hour`, `day_type`, `month`
  - weather forecast
  - electricity pricing forecast
  - carbon intensity
  - district current load, district predicted peak
  - coordinator target: charge/discharge/hold priority

### 5.3 빌딩 agent의 출력

각 Building Agent는 단순 action 값만 내기보다 설명 가능한 decision을 내는 것이 좋다.

```json
{
  "building_id": "Building_1",
  "recommended_action": -0.34,
  "mode": "discharge",
  "reason": "district peak expected within 2 hours and SOC is sufficient",
  "confidence": 0.82,
  "constraints": {
    "soc_after_action_estimate": 0.44,
    "nominal_power_ok": true
  }
}
```

그 다음 Constraint Guard가 action을 최종 clipping한다.

### 5.4 Coordinator 정책

Coordinator는 개별 agent를 직접 대체하지 않고, 도시 전체 운영 목표를 broadcast해야 한다.

예시:

```json
{
  "time_step": 4210,
  "district_mode": "peak_shaving",
  "target": {
    "max_district_import_kwh": 52.0,
    "ramp_limit_kwh": 8.0,
    "carbon_priority": "medium",
    "cost_priority": "high"
  },
  "building_budget": {
    "Building_1": {"preferred_mode": "discharge", "max_discharge_action": -0.45},
    "Building_2": {"preferred_mode": "hold", "max_discharge_action": -0.10}
  }
}
```

### 5.5 Baseline 비교 기준

새 구조의 성능은 최소 다음 baseline과 비교해야 한다.

| baseline | 의미 |
| --- | --- |
| No control | storage action 없이 자연 부하/PV만 반영 |
| BasicRBC | 기존 시간 기반 규칙 |
| OptimizedRBC 또는 BasicBatteryRBC | 더 나은 rule-based baseline |
| SAC/MARLISA | 기존 RL/MARL 계열 |
| Agent-Mesh | 새 agentic 구조 |

Board 뷰의 핵심 비교는 `BasicRBC` 대비 Agent-Mesh 개선율로 잡는 것이 가장 설명 가능하다.

## 6. 현재 데이터셋 기반 운영 인사이트

기존 `citylearn_challenge_2022_phase_all` 기준 계산 결과는 다음과 같았다. `citylearn_challenge_2022_phase_all_plus_evs`는 동일한 17개 빌딩 축에 EV charger와 washing-machine profile을 추가하므로, Board에서는 이 확장 설비를 명시해야 한다.

| 항목 | 값 |
| --- | ---: |
| 가격 min/avg/max | 0.21 / 0.2731 / 0.54 |
| 탄소 min/avg/max | 0.0704 / 0.1565 / 0.2818 |
| 외기온 min/avg/max | 5.6 / 16.84 / 32.2 |
| 빌딩별 연간 non-shiftable load 범위 | 약 6,462 ~ 14,711 |
| 빌딩별 peak load 범위 | 약 4.41 ~ 8.85 |

빌딩별 부하 규모가 다르므로, 단순히 모든 빌딩에 같은 action을 주는 정책은 최적이 아니다. 부하가 큰 빌딩, PV 잠재력이 큰 빌딩, SOC 여유가 있는 빌딩을 구분해야 한다.

운영 관점에서 우선 감시할 빌딩:

- 높은 연간 부하: `Building_17`, `Building_10`, `Building_11`, `Building_16`
- 높은 peak load: `Building_17`, `Building_10`, `Building_16`, `Building_1`
- 낮은 연간 부하이지만 storage 활용 여지가 있는 빌딩: `Building_15`, `Building_3`, `Building_9`

## 7. 구현 시 주의사항

### 7.1 UI/feature 정의와 실제 데이터셋 차이

현재 앱 feature list와 Board 기준은 `citylearn_challenge_2022_phase_all`다. 확인된 학습 완료 artifact도 같은 데이터셋 기준이며, 모델 클래스는 `citylearn.agents.sac.SACRBC`다.

구현 선택지는 두 가지다.

1. 현재 Board의 phase_all 구성을 유지한다.
   - Board는 `phase_all` schema를 기준으로 배터리, PV, net load 상태를 표시한다.
   - SACRBC artifact 존재 여부를 Board에 명시한다.
   - 단, 실제 CityLearn environment step과 Agent-Mesh action API는 아직 연결되어 있지 않음을 명시한다.

2. 실제 실행 연동을 구현한다.
   - backend에서 CityLearn environment를 생성하고 `schema.json`/CSV를 읽는다.
   - baseline runner(`BasicRBC`, `OptimizedRBC`, `BasicBatteryRBC`, `SAC`, `MARLISA`)와 Agent-Mesh action endpoint를 분리한다.
   - reward와 KPI는 실제 environment step 결과로 Board에 반환한다.

### 7.2 Reward와 KPI를 분리해서 생각해야 한다

기존 시스템은 reward로 학습하고 KPI로 평가한다. 새 agentic 구조에서는 reward-like objective와 KPI dashboard를 분리하는 편이 좋다.

- action 결정: 짧은 horizon의 operational objective
- 평가: 24h/72h/annual KPI
- 설명: “왜 충전/방전했는가”를 action과 함께 기록

### 7.3 중앙집중형과 분산형을 혼합해야 한다

현재 schema는 `central_agent=false`다. 따라서 빌딩별 agent가 action을 낸다.

하지만 도시전력 목표는 district-level이다. 새 구조는 다음 hybrid가 적절하다.

- 분산 실행: Building Agent가 각 빌딩 action 결정
- 중앙 조정: Coordinator가 district peak/ramping/price/carbon 목표 제공
- 중앙 검증: Guard/Evaluator가 action과 KPI를 검증

### 7.4 현재 MeshBoard Board 구현 상태

현재 Board는 `CityLearn_old_system`의 Python runtime을 직접 step 하지 않는다. SAC/MARLISA도 실제 inference로 연결되어 있지 않다. Board의 Baseline/Agent-Mesh 곡선은 프론트엔드 deterministic preview이며, 모델 선택은 “실행 결과 선택”이 아니라 “비교 시나리오 선택”이다.

따라서 사용자에게 다음을 명시해야 한다.

- dataset 기준: `citylearn_challenge_2022_phase_all` schema verified
- checkpoint 기준: `CityLearn_old_system/citylearn/best_inference_bundle.pt` detected, model `SACRBC`
- live runtime: not connected
- baseline: BasicRBC/OptimizedRBC/BasicBatteryRBC/SACRBC checkpoint/SAC/MARLISA 선택 가능
- Agent-Mesh: not configured/demo/configured-agents preview 선택 가능
- 실제 반영을 위해서는 backend CityLearn runner와 Agent-Mesh action API가 필요

## 8. 결론

현재 phase_all Board의 핵심 목표는 “각 빌딩의 배터리 제어를 도시 전체 grid 관점의 피크/비용/탄소/ramping 목표와 맞추는 것”이다. EV charger와 washing-machine 제어는 plus_evs 또는 three-phase electrical service 계열로 확장할 때 별도 action space로 다룬다.

기존 BasicRBC는 설명 가능하고 안정적인 baseline이지만 시간 기반 규칙이라 가격, 탄소, forecast, 빌딩별 상태 차이를 충분히 활용하지 못한다. 기존 SAC/MARLISA는 학습 기반 최적화를 제공하지만 reward 설계와 학습 안정성에 민감하다.

따라서 MeshBoard의 agentic 접근은 다음 방향이 가장 타당하다.

1. City Grid Coordinator가 도시 목표를 계산한다.
2. Building Agent는 빌딩별 관측과 coordinator target을 받아 action을 제안한다.
3. Constraint Guard가 물리 제약을 보장한다.
4. Evaluator가 BasicRBC 대비 KPI 개선을 측정한다.
5. Board는 총 전력 소비, 비용, 탄소, 피크, ramping, 빌딩별 SOC를 실시간으로 보여준다.

이 구조를 기준으로 구현하면 기존 CityLearn benchmark의 의미를 유지하면서도, “빌딩별 agent가 하나의 독립 노드로 협업하는 도시 전력 운영 시스템”으로 확장할 수 있다.

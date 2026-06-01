# CHESCA Implementation Notes

## Reference

이 프로젝트의 원본은 `CHESCA-main`에 포함된 공식 공개 코드와 보충자료를
실행 기준으로 사용합니다.

- Official code: `CHESCA-main/`
- Included supplement: `CHESCA-main/Supp_material.pdf`
- Evaluation environment required by the official README:
  `CityLearn==2.1b12`
- Vendored official evaluation runtime: `third_party/CityLearn-2.1b12/`

## Source-Level Reading

공식 `checa/agent.py`의 처리 순서는 다음과 같습니다.

1. `ForecastAgent`가 outdoor temperature, solar generation, DHW demand,
   non-shiftable load를 예측합니다.
2. `initial_actions()`가 outage 상태를 확인하고 cooling PID와 DHW schedule
   기반 action을 만듭니다.
3. `refine_actions_with_battery_controller()`가 정상 운전 중인 각 건물에
   대해 독립적으로 battery tree-search를 수행합니다.
4. 해당 건물의 예상 부하가 자체 평균/표준편차 범위를 벗어나면 DHW action을
   보정합니다. 코드 기본 parameter에서 cooling reduction은 `0.0`입니다.

코드상 refinement는 각 건물의 자체 이력에 의존하며, 다른 건물의 flex
offer를 받아 district action을 함께 선택하는 절차는 없습니다.

## Mesh Extension Boundary

`chesca_mesh`는 공식 `Checa`를 상속하고
`refine_actions_with_battery_controller()` 경계만 확장합니다.

- 먼저 공식 메서드를 호출해 공식 CHESCA action을 얻습니다.
- 각 정상 운전 건물은 공식 배터리 action 주변의 feasible flex offer를
  생성합니다.
- peer들은 공식 action에서 예상되는 부하, 가능한 상하향 유연성, SOC,
  district proposal, district target, shadow signal을 broadcast합니다.
- 각 peer는 받은 district 신호와 자체 SOC reserve 비용을 기준으로 offer를
  선택합니다.
- outage 건물, 공식 HVAC/DHW/forecast 로직은 변경하지 않습니다.

이는 LLM, KG, 강화학습 없이 통신 자체가 district-level 조정을 추가하는지
검증하기 위한 첫 CHESCA 기반 mesh입니다. 공식 action은 언제나 선택지로
남지만, 모든 변경을 중앙 acceptance gate로 억지 승인하는 방식은 사용하지
않습니다. 각 peer가 동일한 메시지 집합에 반응해 자신의 offer를 선택합니다.

## Validation

가장 먼저 확인할 비교는 다음과 같습니다.

1. `chesca_official`이 공식 CityLearn schema에서 정상 실행되는지 확인합니다.
2. 동일 schema에서 `chesca_mesh`의 공식 KPI 변화율을 비교합니다.
3. `mesh_messages.csv`와 `mesh_negotiations.csv`에서 실제로 어느 시점에
   flex가 바뀌었고 predicted district load가 어떻게 변했는지 확인합니다.
4. phase 3의 여러 schema에 걸쳐 한 데이터에만 우연히 맞는 현상인지
   확인합니다.

성능 향상은 구현만으로 보장되지 않습니다. 이 구조의 장점은 실패하더라도
공식 CHESCA 대비 어떤 메시지와 action 변화가 악화를 일으켰는지 추적할 수
있다는 점입니다.

## Paper Public/Private Cost

본문 Section 5.1은 CityLearn 2023 최종 비용 가중치를 다음과 같이
정의합니다.

```text
cost = 0.30 * comfort
     + 0.10 * emissions
     + 0.30 * grid
     + 0.30 * resilience
```

Grid 내부에서는 `ramping_average`,
`daily_one_minus_load_factor_average`, `daily_peak_average`,
`annual_peak_average`(display name: All-time peak)를 동일 가중 평균합니다.
Resilience 내부에서는
`one_minus_thermal_resilience_proportion`과
`power_outage_normalized_unserved_energy_total`을 동일 가중 평균합니다.

번들 schema로 다음 비교를 재현합니다.

| Cost | Schemas | Buildings |
| --- | --- | ---: |
| Public Cost | `citylearn_challenge_2023_phase_2_online_evaluation_1/2/3` | 3 |
| Private Cost | `citylearn_challenge_2023_phase_3_1/2/3` | 6 |

각 세 schema는 동일한 부하 자료에 서로 다른 power outage seed를 지정합니다.
`BenchmarkSuite.compare_public_private_costs()`는 각 split에서 세 실행의
반올림 전 cost를 평균하여 `leaderboard_cost`로 저장합니다.

공식 `CityLearn==2.1b12`의 `evaluate_citylearn_challenge()`는 위 여덟
하위 지표의 가중합을 `average_score`로 반환합니다. 평가기는 동일 수식을
독립 계산해 `average_score`와 일치하는지 확인한 후 이 값을
`challenge_cost`로 기록합니다.

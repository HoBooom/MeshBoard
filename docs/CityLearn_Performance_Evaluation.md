# CityLearn 4-Mode Performance Evaluation

평가일: 2026-06-01 (snapshot 버그 수정 후 재실행본) · 하니스: `backend/scripts/eval_modes.py`
LLM: `anthropic/claude-sonnet-4-6` (RUNYOUR, 실제 호출) · LLM Planner `iter=3`, MACRO-MESH `rounds=3(실효 2)`

> **수정 이력:** 초기 실행본은 snapshot 빌더가 CityLearn 시계열의 *아직 시뮬레이션되지 않은
> placeholder 슬롯*(`series[time_step]`, 값 0)을 읽어 planner에게 "모든 빌딩 부하=0, SOC=0"을 전달하는
> 버그가 있었다. 이로 인해 deterministic/LLM/MACRO 결과가 왜곡되었다(SARBC는 env `obs`를 직접 써 무관).
> `_decision_index = time_step − 1`(직전 실현 상태)로 수정 후 전 모드 재실행한 결과가 본 문서다.

---

## 1. 개요

baseline(SARBC) · Deterministic Grid-Agent · LLM Planner · MACRO-MESH 4개 모드를 **동일한 실제
`CityLearnEnv`**(seed=0)에서 step 단위로 구동하고, 각 모드의 빌딩별 배터리 action을 `env.step()`에
주입한 뒤 `env.evaluate()`로 CityLearn Challenge 공식 KPI를 산출했다.

| KPI | 의미 | 산출(`env.evaluate()` district) |
|---|---|---|
| `comfort_cost` | 실내 온도 불편도 | `discomfort_proportion` |
| `emissions_cost` | 탄소 배출 | `carbon_emissions_total` |
| `grid_cost` | ramping·load factor·daily/annual peak 평균 | 4개 평균 |
| `resilience_cost` | outage·thermal resilience | 2개 평균 |
| `challenge_cost` | 위 항목 평균(최종) | 산출 가능 항목 평균 |

> **해석:** 모든 값은 control/baseline 비율. `<1.0` 우수, `=1.0` baseline 동일, `>1.0` 열위.

---

## 2. 방법론

- 모드마다 새 env. SARBC는 `agent.predict()`, 나머지는 매 step **직전 실현 env 상태로 board snapshot을
  구성**해 grid-agent 파이프라인(`run_deterministic_plan`/`run_llm_planner_loop`/
  `run_macro_mesh_negotiation`) 호출 → 반환된 `CityLearnPlan`의 배터리 값을 주입.
- LLM 호출: `City Grid Coordinator`(LLM Planner), `Building Battery Agent`×N(MACRO-MESH) 실제 Sonnet 4.6.
- **공정 비교:** KPI는 누적 비율이라 step 수가 다르면 비교 불가 → **공통 horizon(5/20/40)에서만** 비교.
- **step 수(비용 제어):** `sarbc/deterministic=40`, `macro_mesh=20`, `llm_planner=5`.

| 데이터셋 | 빌딩 | action/빌딩 | comfort | resilience |
|---|---|---|---|---|
| `citylearn_challenge_2022_phase_all` | 17 | 1(배터리) | N/A(미지원) | N/A(미지원) |
| `citylearn_challenge_2023_phase_1` | 3 | 3(dhw·배터리·cooling) | 지원 | N/A(1~40 step 내 outage 없음) |

---

## 3. step당 소요 시간 (실측)

| 데이터셋 | 모드 | 평균 s/step | step 수 | 비고 |
|---|---|---:|---:|---|
| 2022 | sarbc / deterministic | 0.01 | 40 | LLM 없음 |
| 2022 | macro_mesh | 42.23 | 20 | 17빌딩 × 2 round 병렬 |
| 2022 | llm_planner | 91.06 | 5 | coordinator tool 루프 |
| 2023 | sarbc / deterministic | 0.00 | 40 | LLM 없음 |
| 2023 | macro_mesh | 18.44 | 20 | 3빌딩 × 2 round |
| 2023 | llm_planner | 174.80 | 5 | coordinator tool 루프 |

> MACRO-MESH step당 시간 = **2 round × (빌딩 동시호출 중 최장 지연)**. 빌딩 수↑ → tail latency↑
> (2022 17빌딩 42s > 2023 3빌딩 18s). round 수는 `ROUND_INDEX_MAX=1`로 max 2 고정.

---

## 4. 결과 — 2022 (`citylearn_challenge_2022_phase_all`, 배터리 전용)

comfort/resilience는 데이터셋 미지원으로 N/A. `challenge_cost`는 emissions·grid 평균.

| 모드 | horizon | emissions | grid | **challenge** | cost_total |
|---|---:|---:|---:|---:|---:|
| sarbc | 5 | 1.000 | 0.924 | **0.962** | 1.000 |
| deterministic | 5 | 1.717 | 4.298 | **3.007** | 1.711 |
| macro_mesh | 5 | 1.000 | 0.924 | **0.962** | 1.000 |
| llm_planner | 5 | 1.000 | 0.924 | **0.962** | 1.000 |
| sarbc | 20 | 1.728 | 0.589 | **1.158** | 1.704 |
| deterministic | 20 | 2.517 | 1.222 | **1.870** | 3.056 |
| macro_mesh | 20 | 1.017 | 1.001 | **1.009** | 1.032 |
| sarbc | 40 | 1.044 | 0.772 | **0.908** | 0.981 |
| deterministic | 40 | 1.277 | 1.047 | **1.162** | 1.313 |

**비교(동일 horizon):**
- **h=5:** sarbc·macro·llm = 0.962로 동률(배터리 워밍업 구간 §7). deterministic 3.007 — 빈 배터리를
  공격적으로 충전해 grid가 4.3까지 악화.
- **h=20:** **macro_mesh 1.009**로 baseline 근처(워밍업 후 소폭 충·방전, 미세 열위). sarbc는 grid를
  0.589로 크게 낮추나 emissions(1.728)가 튀어 1.158. deterministic 1.870 최열위.
- **h=40:** **sarbc 0.908**이 grid 0.772로 최우수. deterministic 1.162.

---

## 5. 결과 — 2023 (`citylearn_challenge_2023_phase_1`, comfort 활성)

comfort 산출. resilience는 1~40 step 내 outage 없어 N/A. SARBC는 학습 번들 비호환으로 **BasicRBC** 대체(§7).

| 모드 | horizon | comfort | emissions | grid | **challenge** | cost_total |
|---|---:|---:|---:|---:|---:|---:|
| sarbc(RBC) | 5 | 0.000 | 1.779 | 1.065 | **0.948** | 1.780 |
| deterministic | 5 | 0.000 | 2.509 | 2.724 | **1.744** | 2.495 |
| macro_mesh | 5 | 0.000 | 1.000 | 0.849 | **0.616** | 1.000 |
| llm_planner | 5 | 0.000 | 1.000 | 0.849 | **0.616** | 1.000 |
| sarbc(RBC) | 20 | 0.164 | 1.273 | 0.979 | **0.805** | 1.255 |
| deterministic | 20 | 0.258 | 0.696 | 1.035 | **0.663** | 0.600 |
| macro_mesh | 20 | 0.258 | 0.566 | 1.054 | **0.626** | 0.479 |
| sarbc(RBC) | 40 | 0.541 | 1.500 | 0.979 | **1.006** | 1.486 |
| deterministic | 40 | 0.631 | 0.530 | 0.959 | **0.707** | 0.508 |

**비교(동일 horizon):**
- **h=5:** **macro·llm = 0.616** 최우수(grid 0.849·comfort 0, 워밍업 구간이라 사실상 무제어=baseline).
  sarbc(RBC) 0.948, deterministic 1.744(과충전).
- **h=20:** **macro_mesh 0.626 ≈ deterministic 0.663**. macro는 emissions를 0.566으로 절감(단 grid 1.054 소폭↑).
  sarbc(RBC) 0.805.
- **h=40:** **deterministic 0.707**이 sarbc(RBC) 1.006을 능가 — 배터리 차익거래로 emissions(0.530)·cost(0.508) 절감.

---

## 6. 종합

1. **2022 장기(h=40):** 학습된 **SARBC(0.908)**가 최적(피크/그리드 개선). MACRO-MESH는 워밍업 후
   소폭 충·방전해 baseline 근처(1.009).
2. **2023:** 단기(h=5)는 워밍업이라 macro·llm=baseline(0.616). 장기(h=40)는 **Deterministic(0.707)**이
   RBC를 능가. macro(h=20)는 emissions 절감이 두드러짐.
3. **Deterministic의 초반 악화:** 빈 배터리를 즉시 충전 → h=5에서 두 데이터셋 모두 최열위(2022 3.007,
   2023 1.744). step 누적 시 완화.

---

## 7. 한계 및 주의사항

- **배터리 워밍업 구간 → llm_planner(5 step)는 신호 없음.** 모든 배터리가 SOC=0으로 시작하므로 초기 ~5 step은
  방전할 전력이 없어 모든 모드가 hold→ KPI=baseline(0.962/0.616). **llm_planner는 이 구간만 측정되어 LLM
  Planner의 실제 성능을 반영하지 못한다.** macro_mesh(20 step)는 워밍업 이후 분기.
- **comfort/resilience N/A:** 2022는 thermal·outage 동역학 부재. 2023은 comfort 산출되나 평가 구간 내
  outage 이벤트 없어 resilience N/A. 임의값으로 채우지 않음.
- **2023 SARBC = BasicRBC 대체:** 학습 번들(`best_inference_bundle.pt`)은 2022(17빌딩/1액션) 전용 →
  2023(3빌딩/3액션) shape 불일치, 미학습 SACRBC는 SAC 정규화 통계 부재로 실패. RBC로 대체(`sarbc_kind=rbc_fallback`).
- **모드별 step 수 상이** → 공통 horizon에서만 비교.
- **배터리 전용 제어:** grid-agent/LLM/MACRO 모드는 배터리만 제어(2023의 dhw/cooling=0).

---

## 8. 재현

```bash
cd /Users/hobongs/Desktop/HoBong_study/26-1/meshboard
uv run --project backend python backend/scripts/eval_modes.py \
  --modes noctrl,sarbc,deterministic,macro_mesh,llm_planner \
  --mode-steps "noctrl:40,sarbc:40,deterministic:40,macro_mesh:20,llm_planner:5" \
  --horizons "5,20,40" --planner-iter 3 --mesh-rounds 3 \
  --datasets citylearn_challenge_2022_phase_all,citylearn_challenge_2023_phase_1 \
  --ckpt docs/_eval_checkpoint.json
```

- 하니스: `backend/scripts/eval_modes.py` · 원시 결과: `docs/_eval_checkpoint.json` (모드별 `kpis_by_horizon`)
- 보드 물리지표(총전력소비·피크·Reward 등)는 [`CityLearn_Board_Metrics.md`](./CityLearn_Board_Metrics.md) 참조.

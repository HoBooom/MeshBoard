# CityLearn Grid-Agent 보드 지표 결과 (총전력소비·전력·탄소배출·피크·Reward)

평가일: 2026-06-01 (snapshot 버그 수정 후 재실행본) · 하니스: `backend/scripts/eval_modes.py`
원시 결과: `docs/_eval_checkpoint.json` · LLM: `anthropic/claude-sonnet-4-6` (실제 호출)

> Grid-Agent CityLearn 보드(WorkspacePage)에 표시되는 **물리량 지표**를 산출한 결과다.
> challenge KPI(비율)는 [`CityLearn_Performance_Evaluation.md`](./CityLearn_Performance_Evaluation.md) 참조.
> **수정 이력:** snapshot 빌더가 placeholder(0) 슬롯을 읽던 버그를 `_decision_index=time_step−1`로 수정 후 재실행본.

---

## 1. 지표 정의 (프론트엔드 `WorkspacePage.cityLearnMetrics`와 동일)

각 step의 **제어된 district net load 시계열** `L`(배터리 action 반영, kWh)로부터 계산.

| 보드 지표 | 단위 | 계산식 |
|---|---|---|
| 총 전력 소비량 | kWh | `Σ L` |
| 전력 비용 | $ | `Σ L × 0.18` |
| 탄소 배출량 | kgCO2 | `Σ L × 0.42` |
| 피크 부하 | kW | `max(L)` |
| 누적 Reward | pts | `Σ −(max(L,0)^1.05)` |

> 비용·탄소는 총소비에 비례(0.18 $/kWh, 0.42 kgCO2/kWh)하므로 개선율은 총소비와 동일.
> baseline = **`noctrl`**(배터리 idle). 개선율 = `(noctrl − mode)/noctrl × 100` (양수=절감).

---

## 2. 결과 — 2022 (`citylearn_challenge_2022_phase_all`, 17빌딩)

| 모드 | h | 총소비(kWh) | Δ소비 | 비용($) | 탄소(kg) | 피크(kW) | Δ피크 | Reward |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **noctrl** | 5 | 62.22 | – | 11.20 | 26.13 | 17.19 | – | −70.64 |
| sarbc | 5 | 62.22 | +0.0% | 11.20 | 26.13 | 17.19 | +0.0% | −70.64 |
| deterministic | 5 | 116.22 | −86.8% | 20.92 | 48.81 | 35.19 | −104.7% | −136.33 |
| macro_mesh | 5 | 62.22 | +0.0% | 11.20 | 26.13 | 17.19 | +0.0% | −70.64 |
| llm_planner | 5 | 62.22 | +0.0% | 11.20 | 26.13 | 17.19 | +0.0% | −70.64 |
| **noctrl** | 20 | 227.19 | – | 40.90 | 95.42 | 26.96 | – | −257.74 |
| sarbc | 20 | 226.35 | +0.4% | 40.74 | 95.07 | **17.19** | **+36.2%** | −255.85 |
| deterministic | 20 | 326.25 | −43.6% | 58.73 | 137.03 | 35.19 | −30.5% | −377.14 |
| macro_mesh | 20 | 230.27 | −1.4% | 41.45 | 96.71 | 27.21 | −0.9% | −261.52 |
| **noctrl** | 40 | 486.52 | – | 87.57 | 204.34 | 33.38 | – | −555.16 |
| sarbc | 40 | 485.90 | +0.1% | 87.46 | 204.08 | **27.74** | **+16.9%** | −552.44 |
| deterministic | 40 | 588.37 | −20.9% | 105.91 | 247.11 | 35.19 | −5.4% | −677.67 |

> `llm_planner` 5 step, `macro_mesh` 20 step까지만 구동.

**관찰(2022):**
- **SARBC = 피크 셰이빙형.** 총소비는 baseline과 사실상 동일(±0.4%)하나 **피크를 크게 절감**
  (h=20 26.96→17.19 kW **+36.2%**, h=40 33.38→27.74 kW **+16.9%**). 5개 지표 중 피크에서 유일하게 큰 이득.
- **Deterministic = 과충전형.** 빈 배터리를 즉시 충전해 소비·피크·탄소 모두 악화(h=5 −87%). step 누적 시 완화(h=40 −21%).
- **MACRO-MESH:** 워밍업 후 소폭 충·방전(h=20 소비 −1.4%, 피크 −0.9%) — baseline 대비 미세 열위.
- **LLM Planner:** 5 step 전부 워밍업 → baseline과 동일(§4 참조).

---

## 3. 결과 — 2023 (`citylearn_challenge_2023_phase_1`, 3빌딩)

SARBC는 BasicRBC 대체, grid-agent/LLM/MACRO는 배터리만 제어.

| 모드 | h | 총소비(kWh) | Δ소비 | 비용($) | 탄소(kg) | 피크(kW) | Δ피크 | Reward |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **noctrl** | 5 | 6.79 | – | 1.22 | 2.85 | 1.50 | – | −6.89 |
| sarbc(RBC) | 5 | 10.54 | −55.3% | 1.90 | 4.43 | 2.26 | −49.9% | −10.94 |
| deterministic | 5 | 13.71 | −102.1% | 2.47 | 5.76 | 3.90 | −159.3% | −14.44 |
| macro_mesh | 5 | 6.79 | +0.0% | 1.22 | 2.85 | 1.50 | +0.0% | −6.89 |
| llm_planner | 5 | 6.79 | +0.0% | 1.22 | 2.85 | 1.50 | +0.0% | −6.89 |
| **noctrl** | 20 | 39.67 | – | 7.14 | 16.66 | 9.77 | – | −41.88 |
| sarbc(RBC) | 20 | 87.36 | −120.2% | 15.72 | 36.69 | 9.76 | +0.1% | −95.03 |
| deterministic | 20 | 49.26 | −24.2% | 8.87 | 20.69 | 10.02 | −2.5% | −52.33 |
| macro_mesh | 20 | 39.67 | +0.0% | 7.14 | 16.66 | 9.77 | +0.0% | −41.88 |
| **noctrl** | 40 | 72.46 | – | 13.04 | 30.43 | 9.77 | – | −75.92 |
| sarbc(RBC) | 40 | 225.33 | −211.0% | 40.56 | 94.64 | 10.96 | −12.1% | −247.13 |
| deterministic | 40 | 81.03 | −11.8% | 14.58 | 34.03 | 10.02 | −2.5% | −85.27 |

**관찰(2023):**
- **BasicRBC(=sarbc 대체)는 소비 폭증형.** 규칙 기반 충전이 총소비를 크게 늘림(h=40 −211%).
- **Deterministic**은 RBC보다 소비 증가폭이 작고 후반 수렴(h=40 −11.8%).
- **MACRO-MESH:** 2023에서는 모든 horizon에서 baseline과 동일(3빌딩 merged plan이 hold로 수렴).
- **LLM Planner:** 5 step 전부 워밍업 → baseline과 동일.

---

## 4. ⚠️ 핵심 해석 — "LLM 모드가 baseline과 같다"의 진짜 이유

초기 실행본에서 LLM·MACRO가 baseline과 완전히 동일했던 것은 **snapshot 버그**(planner가 부하·SOC를 전부 0으로
봄) 때문이었고, 수정 후에는 **MACRO-MESH(2022)가 baseline과 분기**한다. 남은 동일성은 두 가지 별개 원인이다:

1. **배터리 워밍업(llm_planner=5, 모든 모드 h=5):** 배터리가 SOC=0으로 시작 → 초기 ~5 step은 방전 불가 →
   hold → baseline과 동일. **버그가 아니라 평가 구간이 워밍업뿐**이라 발생. llm_planner는 5 step만 돌려
   이 구간만 측정되었다(LLM Planner 실제 성능 미반영).
2. **MACRO-MESH 2023:** 3빌딩 협상의 merged plan이 hold로 수렴해 baseline 유지(2022 17빌딩은 분기).

→ 즉 현재 보드 지표상 **유의미한 이득은 2022 SARBC의 피크 셰이빙**이며, LLM 모드의 적극적 효과를 보려면
llm_planner를 워밍업 이후(≥10~20 step)까지 연장해야 한다.

---

## 5. 한계

- 누적 지표 → **동일 horizon 비교만 유효**(macro=20, llm=5).
- LLM 모드 비결정적. 2023 SARBC=BasicRBC 대체, 배터리 전용 제어.
- Reward는 보드와 동일한 부하 기반 프록시(`−load^1.05`)로 env 내부 reward와 다름.

---

## 6. 재현

```bash
uv run --project backend python backend/scripts/eval_modes.py \
  --modes noctrl,sarbc,deterministic,macro_mesh,llm_planner \
  --mode-steps "noctrl:40,sarbc:40,deterministic:40,macro_mesh:20,llm_planner:5" \
  --horizons "5,20,40" --planner-iter 3 --mesh-rounds 3 \
  --datasets citylearn_challenge_2022_phase_all,citylearn_challenge_2023_phase_1 \
  --ckpt docs/_eval_checkpoint.json
```
원시 결과: `docs/_eval_checkpoint.json` 의 각 모드 `board_by_horizon`.

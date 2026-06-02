# MACRO-MESH v1 vs v2 구조개선 실험

평가일: 2026-06-02 · 하니스: `backend/scripts/exp_v2.py` + `backend/scripts/macro_mesh_v2.py`
원시결과: `docs/_exp_v2_checkpoint.json` · LLM: `anthropic/claude-sonnet-4-6` (실제 호출)
근거 논문: MACRO-LLM (arXiv [2601.09295](https://arxiv.org/abs/2601.09295))

---

## 1. 목적

[직전 분석](./CityLearn_Board_Metrics.md)에서 기존 macro_mesh(v1)는 논문 MACRO-LLM의 3모듈 중
**CoProposer rollout 검증**과 **Introspector**가 빠진 상태("핵심 모듈 제거 ablation")임을 확인했다.
본 실험은 그 두 모듈을 복원한 **macro_mesh_v2**를 추가하고, 논문이 강조한 상황(돌발상황·에이전트
증가)에서 v1 대비 개선이 실제로 드러나는지 검증한다.

---

## 📘 v2 쉽게 이해하기 (처음 보는 사람용)

> 아래는 배경지식이 없어도 v2가 "무엇을, 왜, 어떻게" 하는지 이해하도록 쓴 설명이다.
> 이미 익숙하면 [§2 구조 차이](#2-v1-vs-v2-구조-차이)로 바로 넘어가도 된다.

### 0-1. 한 문장 + 비유

**"여러 건물이 각자 배터리를 충·방전하는데, 단지 전체 전기요금·피크가 낮아지도록 LLM 에이전트들이
서로 상의해서 결정하게 만든 것"** 이 MACRO-Mesh다. v2는 거기에 **"실행 전에 미리 시뮬레이션해보기"**
와 **"끝나고 복기해서 다음 전략 고치기"** 를 더한 버전이다.

🏢 **아파트 단지 비유**
- **단지(district)** = 17~20개 건물. 단지 전체가 한 순간에 한전에서 끌어 쓰는 전력이 **district net load**.
  이 값의 **최고점(peak)** 이 높을수록 요금·탄소가 커진다. → 낮추는 게 목표.
- **각 건물(building agent)** = 자기 **배터리(ESS)** 를 가진 세대. 할 수 있는 행동은 딱 하나:
  배터리 **action ∈ [−1, 1]**. `+`면 **충전**(전기를 지금 사서 저장 → *그 순간 부하 ↑*),
  `−`면 **방전**(저장분을 꺼내 씀 → *그 순간 부하 ↓*), `0`이면 가만히.
- **관리자(Coordinator)** = 세대들의 제안을 모아 조율하는 사람.
- **제약**: 배터리 잔량(**SOC**, 0~1)이 너무 낮으면(<0.2) 방전 금지, 너무 높으면(>0.9) 충전 금지.
  특정 세대만 계속 희생시키면 안 됨(**fairness**).

### 0-2. 꼭 아는 용어 5개

| 용어 | 쉬운 뜻 |
|---|---|
| **SOC** | 배터리 잔량(0=텅 빔, 1=가득). 방전하려면 잔량이 있어야 함. |
| **district net load / peak** | 단지가 그 순간 쓰는 총 전력 / 그 최고점. **낮을수록 좋음**. |
| **mean-field** | 모든 세대 제안을 일일이 안 보고 **평균·편차 같은 요약 통계**로 압축한 것. 세대가 많아도 가볍게 조율. |
| **rollout(롤아웃)** | 행동을 실제로 하기 전에 **"이렇게 하면 앞으로 어떻게 될까"를 머릿속(수식)으로 미리 돌려보는 것.** |
| **semantic gradient** | 숫자 미분 대신 **"다음엔 이렇게 바꿔라"를 자연어로 적은 개선 방향**. v2의 복기 메모가 이것. |

### 0-3. v2의 3개 모듈 = 세 사람의 역할

```
한 건물 에이전트 안에는 3개의 일이 돌아간다:

①  CoProposer   "나는 0.3만큼 방전할게"  + 미리 시뮬해보고 손해면 철회/수정(rollout)
②  Negotiator   관리자가 17명 제안을 mean-field로 모아 충돌 조정 → 2라운드 재제안
③  Introspector 한 스텝 끝나고 "좋아졌나?" 복기 → "다음엔 더 공격적으로" 전략 메모 갱신
```

- **① CoProposer (제안 + 미리보기)** — 각 세대가 자기 상황(SOC·부하)을 보고 "이만큼 충/방전" 제안.
  **v2의 핵심**: 제안을 그냥 올리지 않고 **rollout으로 검증**한다. 즉 "{제안대로 / 방전만 / 충전만 /
  아무것도 안 함}" 네 가지 후보를 각각 *앞으로 1~2스텝 비용이 얼마일지* 수식으로 미리 계산해서
  **가장 싼 후보를 채택**한다. (실제 실행 전에 손해 보는 행동을 걸러냄)
- **② Negotiator (조율)** — 관리자가 17개 제안을 **mean-field(평균·편차)** 로 요약하고 **충돌**을 찾는다.
  예: "60% 이상이 동시에 방전 → 단지 배터리 고갈 위험", "특정 세대만 과부담(fairness)". 이런 충돌을
  세대들에게 피드백해 **round 2 재제안**을 유도한다. (v1·v2 공통)
- **③ Introspector (복기·학습)** — **v2의 두 번째 핵심**. 한 스텝이 끝나면 결과(reward 추세)를 LLM이 보고
  *"방전이 효과 있었으니 다음엔 조금 더 공격적으로(aggressiveness↑)"* 같은 **자연어 전략 메모**와 조절값을
  만든다. 이 메모는 **다음 스텝 ①CoProposer 프롬프트에 그대로 주입**된다. 즉 **어제의 교훈을 오늘 회의에
  들고 오는 것**. (v1은 매 스텝 백지에서 시작 = 기억 없음)

### 0-4. 한 스텝(step)에서 실제로 벌어지는 일 — 순서대로

```
[현재 단지 상태 읽기] → [건물들 제안(전략 메모 반영, 병렬)] → [관리자 조율 2라운드]
   → [rollout로 최선 후보 검증·채택] → [환경에 적용·결과 관측] → [복기해서 전략 메모 갱신] → 다음 step
```

1. **상태 읽기(snapshot)**: 지금 각 건물의 부하·SOC·태양광 값을 모은다.
2. **제안(CoProposer, 병렬)**: 17개 LLM 에이전트가 *현재 전략 메모와 함께* 각자 action을 제안. 동시에 호출.
3. **조율(Negotiator, 2라운드)**: mean-field·충돌 계산 → 피드백 → 재제안 → 병합(merge).
4. **rollout 검증**: 병합안을 포함한 4개 후보를 surrogate 비용으로 점수 매겨 **최선 채택** + 전략 메모의
   `aggressiveness`로 강도 조절.
5. **적용·관측**: 실제 CityLearn 환경에 배터리 action 주입 → 단지 부하·reward 관측.
6. **복기(Introspector, LLM 1콜)**: reward 추세를 보고 전략 메모·강도를 갱신 → **다음 스텝으로 전달**.

### 0-5. 숫자로 보는 예시 (이해용 가상 시나리오)

```
상황: 오후 피크. 단지 부하 26 kW로 높고, 여러 건물 SOC가 0.5로 여유 있음.

①  각 건물: "방전해서 부하 낮추자" 제안.
②  관리자: mean-field 보니 "거의 다 방전" → over_discharge 충돌 감지 → "일부만 강하게" 피드백.
④  rollout: {전체방전, 방전만, 충전만, 가만히} 비용 비교 → '방전만'이 피크를 26→23으로 가장 많이 낮춤 → 채택.
⑤  적용: 단지 부하 26 → 23 kW. reward 개선(덜 나쁨).
⑥  복기: "방전이 효과적이었다. 다음엔 약간 더 공격적으로." → aggressiveness 1.0 → 1.1, 메모 갱신.
다음 step: 이 메모를 들고 ①부터 다시. (← 이 '기억'이 v1엔 없다)
```

### 0-6. v1과 v2, 딱 세 가지만 다르다

1. **미리보기**: v2는 행동 전에 **rollout로 검증**(손해 보는 행동 가지치기). v1은 LLM 제안을 그냥 씀.
2. **기억**: v2는 **복기 메모를 다음 스텝에 누적**(stateful). v1은 매 스텝 무상태(기억 0).
3. **결과**: 그래서 v2는 **더 적은 action(평균 1~2개)으로 더 좋은 결과**를 내고, **건물 수가 늘거나
   돌발상황에서도 조정이 안 무너진다**(아래 §4~5 결과로 확인).

### 0-7. 코드로 어디에 있나

| 개념 | 위치 |
|---|---|
| 전략 메모 주입 proposer (①) | `StrategyProposer` — `app/services/citylearn_macro_mesh_v2.py` |
| rollout 검증 (① 미리보기) | `rollout_revise(...)` (후보 4종 + surrogate 비용 `_plan_value`) |
| 조율 (②) | v1 재사용: `Negotiator`/`MeanFieldAggregator`/`ConflictDetector` (`citylearn_macro_mesh.py`) |
| 복기·전략 갱신 (③) | `introspect(...)` (LLM semantic gradient) |
| step 간 기억(stateful) | 실험: `MacroMeshV2Controller` / 보드: workspace별 `_V2_STRATEGY_CACHE` |
| 보드 연동(모드 선택) | `run_macro_mesh_v2_negotiation(...)` → `/citylearn/macro-mesh/negotiate` |

---

## 2. v1 vs v2 구조 차이

| 모듈 | v1 (기존) | v2 (신규) |
|---|---|---|
| CoProposer **rollout 검증** | ✗ 단발 LLM 제안 | ✅ k-step surrogate(즉시부하+peak+ramp+SOC건강도)로 후보집합 평가→최선 채택 |
| **Introspector** (semantic gradient) | ✗ 없음 | ✅ 매 step LLM 1콜로 reward 추세 반성→자연어 전략+aggressiveness/discharge_bias 갱신 |
| **stateful (시간축)** | ✗ 매 step 무상태 | ✅ 전략을 step 간 누적해 다음 proposer 프롬프트에 주입 |
| Negotiator(mean-field+conflict, 2 round) | ✅ | ✅ (재사용) |

> v2는 프로덕션 서비스를 수정하지 않고 실험 레이어(`macro_mesh_v2.py`)에 구현, v1 컴포넌트를 재사용.

---

## 3. 실험 설계

- **랜덤 시작** step=4200 (1부터가 아닌 임의 시점, 기록), **초기 SOC=0.5**(워밍업 회피), H=15 step.
- 실험용 schema는 별도 파일로 생성하고 **production schema.json은 미변경**(실제 시스템 17빌딩 유지).
- **E1 normal**: 17빌딩 정상 운영.
- **E2 disturbance**: 17빌딩, step 5~9(5칸)에 **외생 부하 shock +36.73 kWh/step**(정상부하 18.37×2) 주입 —
  데이터에 없는 극단 과부하/정전복구 서지를 모사. agent는 snapshot으로 인지, 실현 board 부하에 반영.
- **E3 building_add**: **더미빌딩 2개 추가(19빌딩)**, 기존 CSV 재사용. 협상 확장성 측정.
- **모드**: noctrl(무제어), sarbc, macro_v1, macro_v2.
- **지표**: 보드(소비/피크/Reward) + env KPI(challenge=emissions·grid) + 협상품질(conflict/consensus/
  mean-field stddev/action수) + 돌발 resilience(shock중 peak·총초과부하·회복 step).

---

## 4. 결과

### E1 정상 (17빌딩, H=15)

| 모드 | 소비(kWh) | 피크(kW) | Reward | KPI chal | consensus | action수 |
|---|---:|---:|---:|---:|---:|---:|
| noctrl | 251.9 | 26.6 | −290.9 | 1.000 | – | – |
| sarbc | 245.5 | 26.0 | −283.5 | 1.180 | – | – |
| macro_v1 | 250.6 | 25.3 | −289.2 | 1.084 | 0.317 | 9.3 |
| **macro_v2** | **233.4** | 25.6 | **−269.1** | 1.190 | 0.279 | **1.9** |

### E2 돌발상황 (shock step 5~9, +36.7 kWh/step)

| 모드 | 소비(kWh) | 피크(kW) | Reward | shock중 초과부하 | 회복 | consensus |
|---|---:|---:|---:|---:|---:|---:|
| noctrl | 435.6 | 63.3 | −521.7 | 179.0 | 1 | – |
| sarbc | 429.1 | 62.8 | −514.4 | 182.8 | 1 | – |
| macro_v1 | 429.8 | 63.0 | −514.1 | 182.5 | 1 | 0.343 |
| **macro_v2** | **418.2** | 63.3 | **−501.5** | **179.0** | 1 | **0.623** |

### E3 빌딩추가 (19빌딩, H=15)

| 모드 | 소비(kWh) | 피크(kW) | Reward | KPI chal | consensus | action수 |
|---|---:|---:|---:|---:|---:|---:|
| noctrl | 287.6 | 30.1 | −334.4 | 1.000 | – | – |
| sarbc | **ERROR** (IndexError) | – | – | – | – | – |
| macro_v1 | 314.9 ⚠️ | 30.4 | −367.8 | 1.267 | 0.418 | 10.7 |
| **macro_v2** | **267.9** | 30.1 | **−311.3** | 1.227 | **0.675** | **1.3** |

---

## 5. 핵심 발견

1. **v2가 보드 지표(소비·Reward)에서 3개 실험 모두 최선.** 정상 233.4 / 돌발 418.2 / 빌딩추가 267.9로
   noctrl·v1·sarbc를 모두 능가.

2. **⭐ 확장성 — 논문 주장 재현.** 빌딩이 17→19로 늘자 **v1은 소비 314.9로 noctrl(287.6)보다 오히려 악화**
   (에이전트 증가 시 조정 붕괴), 반면 **v2는 267.9로 유지·개선**. consensus도 v2 0.675 ≫ v1 0.418.
   → MACRO-LLM이 말한 "모듈(rollout+introspector)이 agent 수 증가에도 조정을 유지한다"가 실제로 나타남.

3. **조정품질·돌발 대응.** 돌발상황에서 v2 consensus 0.623 ≫ v1 0.343, 소비·Reward 최선. shock 흡수(초과부하
   179.0)가 noctrl과 동률로 최소.

4. **Action efficiency.** v2는 평균 **1~2개 action**으로 v1의 9~11개보다 좋은 결과 — rollout 검증이 무의미한
   action을 가지치기. 논문의 action_efficiency 개선과 일치.

5. **⚠️ board vs CityLearn KPI 텐션(정직).** v2는 공격적·결정적 방전으로 **보드 지표는 개선하나, evaluate()
   challenge KPI는 오히려 높음**(정상 1.190, 돌발 1.289). 이는 aggressive discharge가 ramping/load-factor
   변동성을 키워 grid_cost를 악화시키기 때문. 즉 **v2는 운영목표(소비·피크·Reward·조정)에 최적화되지만,
   ramping 평활성을 중시하는 challenge KPI와는 상충**한다. (빌딩추가에서는 v2 1.227 < v1 1.267로 KPI도 우위.)

6. **⭐ RL/규칙의 전이 실패 실증.** sarbc는 학습 SACRBC 번들이 19빌딩에 로드 불가→BasicRBC로 대체했으나
   그마저 **19빌딩에서 IndexError**로 실패. 반면 LLM 기반 v1/v2는 코드 변경 0으로 19빌딩에서 작동.
   → 논문이 지적한 "RL/규칙은 새 토폴로지에 일반화 못 함, LLM은 zero-shot 일반화"를 그대로 보여줌.

---

## 6. 종합

> v1 대비 v2는 **(a) 보드 지표 전반 개선, (b) 에이전트 증가 시 조정 유지(확장성), (c) 돌발상황 조정품질
> 향상, (d) 더 적은 action으로 더 좋은 결과**를 보였다. 이는 논문 MACRO-LLM의 핵심 모듈(CoProposer rollout +
> Introspector)이 실제로 성능을 끌어올린다는 것을 본 환경에서 재현한 결과다. 다만 CityLearn challenge KPI는
> ramping 평활성을 중시해 v2의 공격적 방전과 상충하므로, **목적함수에 따라 v2/v1 선택이 갈린다**(운영 비용·피크
> 절감 → v2, challenge 점수 → 상황별).

---

## 7. 한계

- H=15 step·단일 시작점(4200)·shock 1종 — 통계적 일반화엔 다회 반복·다중 시작점 필요.
- v2 rollout은 실제 env fork가 아닌 **surrogate 모델**(k=2, 즉시부하+SOC건강도). 실제 env k-step rollout으로
  교체 시 더 정확하나 비용 큼.
- Introspector는 부하 기반 reward 프록시(`−load^1.05`)로 반성 — challenge KPI를 직접 보지 않음(그래서 KPI 텐션).
- 더미빌딩은 기존 CSV 재사용(동일 부하 패턴) — 이질적 부하 빌딩이면 결과 달라질 수 있음.
- sarbc 19빌딩 실패는 RBC 구현의 building-count 가정 문제(전이 한계의 한 단면).

---

## 8. 재현

```bash
cd /Users/hobongs/Desktop/HoBong_study/26-1/meshboard
uv run --project backend python backend/scripts/exp_v2.py \
  --start 4200 --horizon 15 --soc 0.5 --dummies 2 --shock-mult 2.0 \
  --exps normal,disturbance,building_add --modes noctrl,sarbc,macro_v1,macro_v2
```
- v2 컨트롤러: `backend/scripts/macro_mesh_v2.py` (StrategyProposer + rollout_revise + introspect + MacroMeshV2Controller)
- 실험 하니스: `backend/scripts/exp_v2.py` · 원시결과: `docs/_exp_v2_checkpoint.json`

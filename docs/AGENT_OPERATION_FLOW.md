# 도시관리 시스템 — 에이전트 동작 과정 정리

> 대상 코드
> - `backend/app/api/v1/citylearn.py` — API 엔드포인트
> - `backend/app/services/agent_runtime.py` — LLM 에이전트 실행 엔진 (LangGraph)
> - `backend/app/services/citylearn_grid_agent.py` — 결정적(deterministic) Grid-Agent 엔진
> - `backend/app/services/citylearn_grid_agent_llm.py` — LLM Planner 재계획 루프
> - `backend/app/services/citylearn_macro_mesh.py` — MACRO-Mesh 분산 협상 엔진
> - `backend/app/services/citylearn_*_publish.py` — 메시지 피드 발행
> - `backend/app/services/citylearn_grid_agent_constants.py` — 임계값/가중치 상수

---

## 0. 한눈에 보기

이 시스템은 CityLearn 기반의 **가상 도시(17개 빌딩, 각 빌딩에 배터리·PV)** 를 운영하면서,
매 step마다 "각 빌딩 배터리를 얼마나 충전/방전할지"를 에이전트가 결정합니다.

에이전트가 동작하는 방식은 **3가지 모드**로 나뉘며, 모두 같은 안전 파이프라인
(Topology 분석 → Plan 제안 → Sandbox 실행 → 제약 검증)을 공유합니다.

| 모드 | 진입점 | 의사결정 주체 | 핵심 특징 |
|------|--------|--------------|-----------|
| **① Deterministic** | `POST /grid-agent/plan` (`use_llm_planner=false`) | 순수 Python 규칙 | LLM 없음, 항상 빠르고 재현 가능 |
| **② LLM Planner** | `POST /grid-agent/plan` (`use_llm_planner=true`) | 단일 LLM (City Grid Coordinator) | LLM이 전체 plan 제안 → 검증 실패 시 재시도 |
| **③ MACRO-Mesh** | `POST /macro-mesh/negotiate` | 17개 빌딩 에이전트의 분산 협상 | 각 빌딩이 자기 배터리만 제안, round 1→2 협상 |

세 모드 모두 **preview-only**(시뮬레이션) 입니다. 실제 board 상태를 직접 바꾸지 않고,
deepcopy한 sandbox 위에서 plan을 적용해 점수를 비교한 뒤 결과만 반환합니다.

```
                    ┌─────────────────────────────────────────┐
   CityLearn board  │  공통 파이프라인 (citylearn_grid_agent)   │
   snapshot ──────► │                                          │
   (17 building,    │  TopologyAnalyzer → ViolationDetector    │
    SOC, net_load,  │        ↓                                  │
    PV, points)     │  [모드별 Planner] → SandboxExecutor       │
                    │        ↓                                  │
                    │  ConstraintValidator → OperatorSummarizer │
                    └─────────────────────────────────────────┘
                                      ↓
                       결과 응답 + 워크스페이스 메시지 피드 발행
```

---

## 1. 입력 데이터: Board Snapshot

모든 모드는 `get_board_snapshot(step, baseline_model, agent_mesh_mode, window)` 가 만든
스냅샷 하나에서 출발합니다 (`citylearn_board.py`).

스냅샷에 담기는 핵심 필드:
- `step` — 현재 시뮬레이션 시점 (0 ~ 8759, 1시간 단위)
- `buildings[]` — 빌딩별 `battery_soc`, `net_load_kwh`/`agent_mesh_net_load_kwh`, `pv_generation_kwh`
- `points[]` — 시계열 그래프용 시점 데이터 (직전 step district load → ramping 계산에 사용)
- `runtime` — `inference_runner_connected`(SACRBC 모델 연결 여부) 등 런타임 상태

`baseline_model` 이 `sacrbc` 면 `citylearn_sacrbc_inference.py` 의 학습된 SAC 모델이
실제 추론을 돌려 baseline 값을 만들고, 그 외에는 CSV 프리뷰/RBC 값을 사용합니다.

또한 워크스페이스의 `metadata_.agent_building_mapping` 에서
"어떤 빌딩이 어떤 에이전트에 할당되어 있는지"를 읽어와 topology와 결합합니다.

---

## 2. 공통 파이프라인 구성요소

`citylearn_grid_agent.py` 에 정의된 6개 모듈이 논문(Grid-Agent)의
TopologyAgent / PlannerAgent / ExecutorAgent / ValidatorAgent / SummarizerAgent 에 대응합니다.

### 2.1 TopologyAnalyzer — 현황 파악
- board snapshot + agent 매핑을 합쳐 `TopologySummary` 생성
- 빌딩별 `ControllableAsset`(SOC, net_load, PV, 담당 agent 유무) 목록화
- district 전체 net load 합산, baseline_model / agent_mesh_mode 추론

### 2.2 ViolationDetector — 위반 탐지
초기(initial) 상태와 plan 적용 후(post-action) 상태 양쪽에서 위반을 찾습니다.

| 위반 타입 | 판정 기준 (상수) |
|-----------|-----------------|
| `peak` | district load > `PEAK_THRESHOLD_KWH`(55 kWh) |
| `ramping` | 직전 step 대비 변화량 > `RAMP_THRESHOLD_KWH`(20 kWh) |
| `soc` | SOC < 0.15(hard lower) 또는 > 0.95(hard upper) |
| `mapping` | 빌딩에 할당된 agent 없음 |
| `invalid_action` | 존재하지 않는 building_id / action 범위 [-1,1] 밖 |
| `fairness` | plan 내 \|action\| 표준편차 > 0.45 |

### 2.3 HeuristicPlanner — 결정적 plan 생성
빌딩별 SOC와 net_load를 보고 충전/방전/보류(hold)를 규칙으로 결정합니다.
- SOC ≤ 0.20(soft lower): 부하 낮으면 충전, 아니면 방전 금지(hold)
- SOC ≥ 0.90(soft upper): 고부하면 방전, 아니면 충전 금지(hold)
- 그 사이: peak 진행 중 + 고부하면 방전, 저부하 + 여유 있으면 소량 충전
- `forbidden_action_keys` 에 들어있는 (building, action) 조합은 회피

### 2.4 SandboxExecutor — 안전한 시뮬레이션
- **snapshot을 deepcopy** 한 뒤 plan을 적용 → 원본은 절대 변경하지 않음
- 각 빌딩의 `battery_soc += action × 0.10`, `net_load += action × 3.2 kWh`
- points 마지막 entry의 district load를 갱신해 ramping 재계산이 가능하도록 함

### 2.5 ConstraintValidator — 승인/거절 결정
- plan 적용 전/후 **score 비교** (`_score`: district load + soc/peak/ramp/fairness penalty)
- `score_after < score_before` (개선됨) **그리고** 새 `invalid_action`/`soc` 위반이 없을 때만 **approved**
- 거절 시 해당 action 키들을 `forbidden_action_keys` 에 누적 → 다음 시도에서 재사용
- 범위를 벗어난 action은 `clipped_actions` 로 보정 기록

### 2.6 OperatorSummarizer — 운영자 요약
step / 승인여부 / 위반 / action 수 / score 변화를 한국어 한 줄 요약으로 생성.

---

## 3. 모드 ① Deterministic (LLM 없음)

진입: `POST /grid-agent/plan` with `use_llm_planner=false`
→ `run_deterministic_plan()` 한 번 호출.

```
analyze() → detect_initial() → HeuristicPlanner.propose()
         → SandboxExecutor.execute() → analyze(sandbox)
         → ConstraintValidator.validate() → OperatorSummarizer.summarize()
```

- 전 과정이 순수 Python, LLM 호출이 전혀 없어 빠르고 재현 가능
- `/grid-agent/analyze` 는 위 중 **analyze + detect_initial 까지만** 수행 (action 미제안)

---

## 4. 모드 ② LLM Planner 재계획 루프

진입: `POST /grid-agent/plan` with `use_llm_planner=true`
→ `run_llm_planner_loop()` (`citylearn_grid_agent_llm.py`).

DB에 시드된 **"City Grid Coordinator"** 에이전트를 매 iteration마다 호출합니다.

```
[준비] analyze → detect_initial → Coordinator agent 로드
                                  └ 없으면 → Heuristic fallback

[반복] iteration = 1 .. max_iterations
  1. _build_planner_prompt() : topology + 위반 + forbidden_keys + 직전 피드백을 JSON으로 직렬화
  2. invoke_agent(Coordinator, prompt)  ← 360초 timeout
  3. _parse_llm_plan() : LLM 응답을 CityLearnPlan으로 파싱 (building_id/action 검증)
        └ 파싱 실패 → iteration을 "schema_failed"로 기록하고 다음 iteration
  4. SandboxExecutor → analyze → ConstraintValidator
  5. validation.approved == true → 즉시 반환 ✔
     아니면 forbidden_action_keys 누적 → 다음 iteration prompt에 재주입

[종료] max_iterations 도달 시 마지막 시도 결과 반환
```

핵심 안전장치:
- LLM 출력은 **반드시 JSON 스키마 + sandbox 검증을 모두 통과**해야 채택
- API 키 없음 / 호출 실패 / 파싱 실패 → 즉시 `HeuristicPlanner` fallback
- 모든 시도(approved/rejected/fallback/schema_failed)는 `iterations[]` 에 trace로 보존

---

## 5. 모드 ③ MACRO-Mesh 분산 협상

진입: `POST /macro-mesh/negotiate` → `run_macro_mesh_negotiation()` (`citylearn_macro_mesh.py`).

여기서는 단일 Coordinator가 아니라 **17개 "Building Battery Agent"** 가
각자 자기 빌딩 배터리만 제안하고, 그 결과를 모아 협상합니다.

```
[준비] analyze → detect_initial → Building Battery Agent 로드

[협상] Negotiator.run() — round 0, round 1 (max_rounds=2)
  각 round:
    1. 17개 빌딩 proposal을 asyncio.gather 로 **병렬** invoke
         · 직렬이면 17×60s≈17분, 병렬이면 ~max(latency)≈60s
         · 빌딩별 45초 timeout, 실패/파싱오류 → 그 빌딩만 heuristic fallback
    2. MeanFieldAggregator : 평균/표준편차/critical_soc_ratio 등 집계
    3. ConflictDetector : over_discharge / soc_risk / fairness / resource_contention 탐지
    4. (다음 round가 있으면) 빌딩별 feedback 생성
         → mean_field + 관련 conflict를 담아 round 2 재제안 유도

[수렴] merge_proposals() : 마지막 round proposal을 최종 plan으로 채택

[검증] 최종 merged_plan을 Grid-Agent의 SandboxExecutor + ConstraintValidator로 재검증
       → OperatorSummarizer 요약
```

각 빌딩 에이전트는 **자기 building_id의 action 1개만** 제안하도록 프롬프트로 제약하며,
SOC<0.2면 방전 금지 / SOC>0.9면 충전 금지 규칙이 프롬프트에 명시됩니다.
LLM을 끄면(`use_llm_proposers=false`) 동일한 협상 구조를 결정적 `_heuristic_propose` 로 수행합니다.

### Conflict 임계값
| Conflict | 조건 |
|----------|------|
| `over_discharge` | round의 60% 이상 빌딩이 동시 방전 |
| `soc_risk` | 적용 시 SOC hard bound 위반 예상 빌딩 존재 |
| `fairness` | \|action\| 표준편차 > 0.40 인 극단 빌딩 존재 |
| `resource_contention` | critical SOC 빌딩 비율 > 30% 인데 방전 시도 |

---

## 6. LLM 에이전트 실행 엔진 (agent_runtime.py)

모드 ②/③ 에서 `invoke_agent()` 가 호출하는 부분입니다.
각 에이전트는 **하나의 LangGraph CompiledGraph** 로 컴파일됩니다.

```
        ┌──────────────┐   tool 요청    ┌───────────────┐
START → │  agent_node  │ ───────────► │  mcp_tool_node │
        │ (LLM 호출)    │ ◄─────────── │ (도구 실행 후    │
        └──────┬───────┘  observation  │  observation)  │
               │ final / 오류 / 최대횟수            └───────────────┘
               ▼
              END
```

- **agent_node**: RunYour AI(OpenAI 호환) 엔드포인트로 LLM 호출 → 응답을 JSON으로 파싱
- **mcp_tool_node**: 요청된 MCP 도구(`TOOL_REGISTRY`)를 실행해 observation을 대화에 추가
- `agent_node ↔ mcp_tool_node` 를 `final` 이 나올 때까지 최대 `MAX_TOOL_STEPS`(6)회 반복

### 응답 프로토콜
RunYour 프록시가 구조적 `tool_calls` 를 일관되게 주지 못하는 문제 때문에,
도구 호출 프로토콜을 **LLM이 출력하는 JSON 텍스트 파싱**으로 단순화했습니다.
LLM은 반드시 아래 둘 중 하나로만 응답해야 합니다:

```json
{"action": "tool",  "tool": "<tool_id>", "arguments": {...}}
{"action": "final", "answer": "<최종 답변>"}
```

- system prompt는 에이전트 레코드(`name`, `purpose`, `approach`, `roles`, 선택한 도구)로 동적 구성
- 상태는 `MemorySaver` 체크포인터에 저장 → `thread_id` 로 resume / interrupt 지원
- 비정상 응답·최대 횟수 초과 시 안전한 fallback 메시지로 종료

---

## 7. 결과의 메시지 피드 발행

plan/negotiate 결과는 워크스페이스 타임라인에 **여러 메시지로 분해**되어 발행됩니다
(`*_publish.py`). 발행 실패는 본 응답을 막지 않습니다 (silent skip + rollback).

- **Grid-Agent** (`publish_plan_message`): `plan_start → tool_call×M → iter_result×K → plan_result`
- **MACRO-Mesh** (`publish_negotiation_messages`): `negotiate_start → (round_start → proposal×N → mean_field → conflict×M) → merged_plan → negotiate_result`
  - 각 building proposal은 `Battery Agent · <building_id>` 가 sender로 표시되어,
    UI에서 빌딩별 발언처럼 보이게 됩니다.
- 해당 에이전트가 워크스페이스에 배치되어 있으면 `sender_type='agent'`, 아니면 `'system'`

---

## 8. 전체 안전 원칙 요약

1. **원본 불변** — 모든 plan은 deepcopy된 sandbox에서만 적용, board 원본은 변경 없음
2. **개선 없으면 거절** — `score_after < score_before` 이고 새 치명 위반 없을 때만 승인
3. **LLM은 검증 위에서만** — LLM 출력은 JSON 스키마 + sandbox 검증을 통과해야 채택
4. **항상 fallback 존재** — LLM 실패 시 결정적 Heuristic 엔진으로 대체
5. **모든 시도 추적** — 승인/거절/fallback이 `iterations[]`·메시지 피드에 trace로 남음
6. **magic number 격리** — 임계값/가중치는 `citylearn_grid_agent_constants.py` 한 곳에만 정의

---

## 부록: 모드 비교 요약

| 항목 | ① Deterministic | ② LLM Planner | ③ MACRO-Mesh |
|------|-----------------|---------------|--------------|
| 의사결정 | 규칙 | 단일 LLM | 17 빌딩 분산 협상 |
| LLM 호출 | 없음 | iteration당 1회 | round당 17회 병렬 |
| 재시도 | 없음 | forbidden_keys 누적 재계획 | round 1→2 협상 |
| timeout | - | 360s | 빌딩당 45s |
| fallback | - | Heuristic | 빌딩별 Heuristic |
| 최종 검증 | ConstraintValidator | ConstraintValidator | ConstraintValidator (공통) |
</content>
</invoke>

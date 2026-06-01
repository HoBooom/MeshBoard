# 실험 계획

> Grid-Agent + MACRO-LLM 통합 아키텍처가 baseline 대비 정량적으로 효과가 있는지,
> 그리고 각 모듈이 실제로 필요한지를 검증하기 위한 실험 설계 문서.

## 1. 실험 목적

1. **Effectiveness**: Agent-Mesh + Grid-Agent + MACRO-LLM 통합이 baseline(BasicRBC / SACRBC 등)보다 district peak / cost / carbon을 더 줄이는가?
2. **Safety**: Validator가 실제로 violation을 차단하는가? Sandbox가 없을 때 대비 얼마나 안전한가?
3. **Necessity (Ablation)**: 각 모듈(Negotiator / Introspector / mean-field / sandbox / replanning loop)을 제거하면 성능/안전이 얼마나 떨어지는가?
4. **Scalability**: 빌딩 수가 늘어날 때 latency, token cost, approval rate가 어떻게 변하는가?
5. **Explainability**: 운영자가 운영자 요약과 reasoning trace만 보고 의사결정을 할 수 있는가?

## 2. Baselines

| ID | 정의 | 데이터 소스 |
| --- | --- | --- |
| `B1_basic_rbc` | CityLearn BasicRBC | 기존 `citylearn_board.py` |
| `B2_optimized_rbc` | CityLearn OptimizedRBC | 기존 |
| `B3_basic_battery_rbc` | CityLearn BasicBatteryRBC | 기존 |
| `B4_sacrbc` | SACRBC checkpoint inference | `citylearn_sacrbc_inference.py` |
| `B5_sac` | CityLearn SAC | 추가 inference bridge |
| `B6_marlisa` | CityLearn MARLISA | 추가 inference bridge |
| `M1_demo_heuristic` | 현재 Board의 demo_heuristic agent_mesh_mode | 기존 |
| `M2_configured_agents_legacy` | 현재 configured_agents 모드 (Grid-Agent 미적용) | 기존 |
| `M3_grid_agent_heuristic` | Phase 1 결정적 Grid-Agent | 신규 |
| `M4_grid_agent_llm` | Phase 2 LLM Planner + Grid-Agent | 신규 |
| `M5_macro_mesh` | Phase 3 MACRO-LLM 분산 협상 + Grid-Agent | 신규 |
| `M6_macro_mesh_introspect` | Phase 5 Introspection 포함 | 신규 |

비교 방향: B1~B6 (baseline) ↔ M1~M2 (현재) ↔ M3~M6 (논문 적용).

## 3. 평가 지표

### 3.1 District-level KPI

| 지표 | 정의 | 단위 |
| --- | --- | --- |
| `district_peak_kwh` | 평가 구간 내 district net load 최대값 | kWh |
| `peak_reduction_kwh` | `baseline_peak - mesh_peak` | kWh |
| `ramping_index` | 평균 \|Δload\| | kWh/step |
| `total_cost` | pricing × net_load 합산 | 단위 가격 |
| `total_carbon` | carbon_intensity × net_load 합산 | kgCO2eq |
| `unmet_demand_ratio` | 부족한 부하 비율 (배터리 부족 시) | % |

### 3.2 Grid-Agent KPI (논문에서 차용)

| 지표 | 정의 |
| --- | --- |
| `approval_rate` | `approved_runs / total_runs` |
| `score_improvement` | `mean(score_before - score_after)` |
| `action_efficiency` | `score_improvement / action_count` |
| `convergence_iterations` | run 당 평균 iteration |
| `new_violation_rate` | new_violations > 0인 run 비율 |
| `runtime_ms` | request start ~ end |

### 3.3 MACRO-LLM KPI

| 지표 | 정의 |
| --- | --- |
| `proposal_conflict_count` | round 당 평균 conflict 수 |
| `consensus_rate` | round 2 종료 시점 합의 도달 비율 |
| `mean_field_compression_ratio` | raw state 크기 / mean_field 크기 |
| `forbidden_repeat_rate` | forbidden_action_key를 재제안한 비율 (낮을수록 좋음) |
| `strategy_update_count` | step 당 평균 semantic_gradient 업데이트 수 |
| `strategy_rollback_count` | 새 전략이 악화시켜 rollback된 횟수 |

### 3.4 Fairness / Safety

| 지표 | 정의 |
| --- | --- |
| `fairness_burden` | 최근 N step `\|action_value\|` building 별 stddev |
| `soc_violation_count` | SOC < 0.15 or > 0.95 도달 횟수 |
| `range_violation_count` | action 범위 외 제안 횟수 (validator가 차단) |

### 3.5 비용 / 운영 효율

| 지표 | 정의 |
| --- | --- |
| `llm_call_count` | step 당 평균 LLM 호출 수 |
| `llm_token_input` | 누적 input 토큰 |
| `llm_token_output` | 누적 output 토큰 |
| `latency_p50_ms`, `latency_p95_ms` | step 처리 시간 분포 |

## 4. 실험 시나리오

### 4.1 Normal Day

- 임의의 평일 24시간 (step N ~ N+23)
- 정상 부하 + 일반 PV 발생량
- 목적: 평상시 KPI 비교

### 4.2 Peak Hour Stress

- step 17~22 사이에 peak가 집중되도록 baseline 조작
- 목적: peak 회피 능력 / fairness 분산 능력

### 4.3 Low SOC Start

- 모든 building 초기 SOC를 0.25로 설정
- 목적: Validator가 무리한 discharge를 막는지 검증

### 4.4 Mapping Sparsity

- 17 building 중 일부 (5/10/15)만 agent 할당
- 목적: mapping violation 처리 및 fallback heuristic 평가

### 4.5 Adversarial Action

- LLM이 의도적으로 범위 외 action / 존재하지 않는 building을 제안하도록 prompt 변조
- 목적: schema/sandbox validation의 hallucination 차단 능력

### 4.6 Long Horizon

- 7일 (step 168) ~ 30일 (step 720) 연속 실행
- Introspector 활성/비활성 비교
- 목적: 운영 중 학습 효과

## 5. Ablation 매트릭스

각 row를 독립 실험으로 측정한다.

| 실험 | 설정 | 기대 결과 |
| --- | --- | --- |
| `A0_full` | M5_macro_mesh 전체 모듈 | 베이스라인 |
| `A1_no_sandbox` | SandboxExecutor 우회, plan 직접 적용 | 안전성 급락, violation 증가 |
| `A2_no_validator` | ConstraintValidator 우회 | new_violation_rate 증가 |
| `A3_no_replanning` | 1회 plan, replanning 금지 | approval_rate 감소 |
| `A4_no_mean_field` | building agent에 raw neighbor state 전체 공유 | 토큰 cost 폭증, latency 증가 |
| `A5_no_negotiation` | round 1만 실행 | conflict 증가, fairness 악화 |
| `A6_no_introspection` | semantic gradient 비활성 | long horizon 시나리오에서 성능 저하 |
| `A7_central_only` | building agent 없이 중앙 LLM 단독 결정 | 빌딩 수 증가 시 latency/quality 악화 |
| `A8_no_forbidden_keys` | forbidden_action_keys 누적 비활성 | 동일 실패 plan 반복 |
| `A9_no_fairness_penalty` | scoring에서 fairness 제거 | 특정 빌딩 부담 집중 |

각 ablation은 4.1 Normal + 4.2 Peak Hour 두 시나리오에서 최소 측정한다.

## 6. 실험 프로토콜

```text
1. seed_agents.py로 City Grid Coordinator, Building Battery Agent ×17, Constraint Guard seed.
2. 평가용 workspace 생성, metadata_.agent_building_mapping 자동 채움.
3. 시나리오별 (step_range, agent_mesh_mode, baseline_model) 조합으로 batch run.
4. 각 run은 commit-preview로 DB에 trace 저장.
5. KPI 집계 endpoint(/citylearn/kpi)로 메트릭 추출.
6. 결과는 CSV/JSON으로 export + Board UI KPI Compare 패널에 표시.
```

각 (모델 × 시나리오) 조합 당 동일 step range를 최소 3회 반복 (LLM 비결정성 평균화).

## 7. 데이터 수집 / 저장

| 종류 | 저장 위치 | 보존 |
| --- | --- | --- |
| Run trace | `citylearn_grid_agent_runs.payload` (JSONB) | 영구 |
| Building action | `citylearn_grid_agent_actions` | 영구 |
| Proposal | `citylearn_macro_proposals` | 영구 |
| Negotiation | `citylearn_macro_negotiations` | 영구 |
| Strategy version | `agent_strategy_versions` | 영구 |
| LLM 원본 응답 (디버깅) | `payload.raw_llm_response` | sanitize 후 30일 |
| 실험 메타데이터 | run.metadata (`scenario_id`, `ablation_flags`) | 영구 |

`scenario_id`, `ablation_flags`를 명확히 기록해야 사후 분석이 가능하다.

## 8. KPI Compare Dashboard 요구사항

Board에 별도 탭 (또는 `/dashboard/kpi`)으로 추가.

- 가로축: 시나리오 (Normal / Peak / Low SOC / ...)
- 세로축: 모델 (B1~M6)
- 셀: 선택한 KPI (peak_reduction / approval_rate / action_efficiency 등)
- 색상: 개선율 (baseline 대비 %)
- 클릭 시 run 목록 + run 상세 trace로 drill-down

Recharts 사용. 별도 BI 도구를 도입하지 않는다.

## 9. 실험 일정 가이드 (예시)

| 주차 | 작업 |
| --- | --- |
| W1 | Phase 1 완료. M3_grid_agent_heuristic vs B1~B4 normal scenario 비교 |
| W2 | Phase 2 완료. M4_grid_agent_llm 추가, adversarial action 시나리오 추가 |
| W3 | Phase 3 완료. M5_macro_mesh 추가, Ablation A0~A5 |
| W4 | Phase 4 완료. KPI dashboard, Ablation A6~A9 |
| W5 | Phase 5 완료. Long horizon + Introspection 비교 |
| W6 | 논문/캡스톤 리포트, failure case 분석 |

## 10. 분석 시 주의점

- LLM 응답 비결정성 → run 최소 3회 평균 + 분산 보고.
- token cost는 모델별로 다르므로 input/output 토큰을 그대로 기록하고, 모델별 단가는 별도 표로 표시.
- approval_rate가 100%인 모델이 반드시 좋은 것은 아니다 (action을 적게 내면 자연스럽게 높아짐). 반드시 `action_efficiency`와 함께 본다.
- baseline은 SACRBC checkpoint inference 결과 그대로를 사용한다 (재학습 비교 X).
- 모든 그래프와 표는 `scenario_id`, `model_id`, `ablation_flags`를 캡션에 명시한다.

## 11. Failure case 분석 양식

각 rejected run을 분석할 때 다음 양식을 채운다.

```yaml
run_id: <uuid>
scenario_id: low_soc_start
model_id: M5_macro_mesh
step: 4212
rejection_reason: "SOC violation introduced on Building_3"
initial_violations:
  - type: soc
    target_id: Building_3
    severity: 0.85
proposed_actions:
  - building_id: Building_3
    action: -0.5
    mode: discharge
why_failed: "Coordinator가 Building_3의 SOC=0.22를 충분히 고려하지 않음"
strategy_update_needed: true
introspection_hint: "SOC < 0.35인 빌딩에는 discharge 요청 보류"
```

이 양식은 introspection 학습 데이터의 prototype이기도 하다. 즉, 실패 분석 자체가 다음 운영 개선의 입력이 된다.

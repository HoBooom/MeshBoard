# Grid-Agent for MeshBoard Overview

> 목적: Grid-Agent 논문의 핵심 개념을 MeshBoard의 CityLearn Agent-Mesh 시스템에 적용하기 위한 짧은 기준 문서.

## 1. 핵심 개념

Grid-Agent의 핵심은 LLM을 직접 제어기로 쓰지 않는 것이다.

```text
LLM Planner = 전략 생성
Simulator / Validator = 수치 검증
Executor = sandbox 적용
Rollback = 실패한 전략 폐기
Summarizer = 운영자 설명 생성
```

MeshBoard에서는 이 원칙을 다음처럼 적용한다.

- LLM은 CityLearn 빌딩 배터리 제어 전략을 제안한다.
- 실제 action 가능 여부는 Python validator가 판단한다.
- 모든 action은 live 환경이 아니라 sandbox state에서 먼저 평가한다.
- 검증에 실패하면 같은 action sequence를 반복하지 않고 재계획한다.
- Board에는 action, 검증 결과, reasoning trace, before/after KPI를 함께 표시한다.

## 2. MeshBoard 대응 관계

| Grid-Agent 논문 | MeshBoard 적용 |
| --- | --- |
| Topology Agent | CityLearn snapshot + workspace agent-building mapping 분석 |
| Planner Agent | district peak/ramping/SOC 문제를 보고 battery action plan 생성 |
| Executor Agent | sandbox state에 `electrical_storage` action 적용 |
| Validator Agent | SOC, action range, peak/ramping, fairness 검증 |
| Summarizer Agent | 운영자용 한국어 요약과 action 근거 생성 |
| Power flow solver | CityLearn runtime 또는 deterministic preview engine |
| Violation | peak 초과, ramping 급증, SOC 위험, agent 미매핑 |
| Rollback | 승인되지 않은 plan 폐기 |

## 3. 현재 프로젝트 기준

현재 MeshBoard의 CityLearn Board는 다음 상태다.

- 데이터셋: `citylearn_challenge_2022_phase_all`
- 시간축: 8760 steps, 1 step = 1 hour
- 빌딩 수: 17
- active action: `electrical_storage`
- baseline: BasicRBC, OptimizedRBC, BasicBatteryRBC, SACRBC, SAC, MARLISA preview
- 연결된 API: `GET /api/v1/citylearn/board`
- 실제 Agent-Mesh action API: 아직 미연결

따라서 Grid-Agent MVP는 `electrical_storage` action만 다룬다.

## 4. 권장 아키텍처

```text
React Workspace Board
  ├─ Board snapshot 조회
  ├─ Grid-Agent plan 실행
  └─ 검증 결과와 action trace 표시

FastAPI
  ├─ citylearn_board.py
  │    └─ 현재 CityLearn snapshot 제공
  ├─ citylearn_grid_agent.py
  │    ├─ TopologyAnalyzer
  │    ├─ ViolationDetector
  │    ├─ HeuristicPlanner
  │    ├─ SandboxExecutor
  │    ├─ ConstraintValidator
  │    └─ OperatorSummarizer
  ├─ tool_catalog.py
  │    └─ LLM Planner용 검증 MCP tool
  └─ agent_runtime.py
       └─ JSON protocol 기반 LLM 실행

PostgreSQL
  ├─ workspaces.metadata.agent_building_mapping
  ├─ optional: citylearn_grid_agent_runs
  └─ optional: citylearn_grid_agent_actions
```

## 5. Runtime Flow

```text
1. Board가 현재 step과 workspace_id로 Grid-Agent plan 요청
2. TopologyAnalyzer가 board snapshot과 workspace metadata를 결합
3. ViolationDetector가 peak/SOC/mapping 문제 탐지
4. Planner가 빌딩별 battery action 후보 생성
5. SandboxExecutor가 복사된 state에 action 적용
6. ConstraintValidator가 score_before/score_after 비교
7. 실패하면 feedback으로 재계획
8. 성공하면 Summarizer가 operator_summary 생성
9. Board가 action overlay와 validation panel 표시
```

## 6. Action Space

CityLearn `phase_all`의 MVP action은 하나다.

| action | 범위 | 의미 |
| --- | ---: | --- |
| `electrical_storage` | `-1.0 ~ 1.0` | 음수는 방전, 양수는 충전, 0은 유지 |

운영 제약:

- SOC가 0.20 미만이면 방전을 피한다.
- SOC가 0.90 초과이면 충전을 피한다.
- 존재하지 않는 `building_id`는 거부한다.
- EV, washing machine, HVAC action은 현재 데이터셋에서 제안하지 않는다.
- live 적용 전 human approval을 기본값으로 둔다.

## 7. Violation Model

| violation | 조건 예시 | 처리 |
| --- | --- | --- |
| `peak` | district net load가 threshold 초과 | SOC 여유 빌딩 방전 |
| `ramping` | 직전 step 대비 load 급변 | charge/discharge 분산 |
| `soc` | SOC 하한/상한 근접 | action clipping 또는 hold |
| `mapping` | 빌딩에 agent 미할당 | warning 및 fallback |
| `fairness` | 특정 빌딩에 부담 집중 | action 분산 |
| `invalid_action` | 범위 초과, 존재하지 않는 빌딩 | plan reject |

## 8. API 초안

```text
GET  /api/v1/citylearn/board
POST /api/v1/citylearn/grid-agent/analyze
POST /api/v1/citylearn/grid-agent/plan
POST /api/v1/citylearn/grid-agent/commit-preview
```

`plan` 응답 핵심 필드:

```json
{
  "run_id": "uuid",
  "step": 4210,
  "initial_violations": [],
  "final_plan": {
    "strategy_summary": "string",
    "actions": [],
    "risk_assessment": "string"
  },
  "validation": {
    "approved": true,
    "score_before": 61.4,
    "score_after": 55.8,
    "feedback": "Approved sandbox plan."
  },
  "iterations": [],
  "operator_summary": "string"
}
```

## 9. LLM Planner Prompt 원칙

Planner prompt에는 다음을 반드시 포함한다.

- 현재 CityLearn step과 district 상태
- violation 목록
- 제어 가능한 빌딩과 SOC
- 사용 가능한 action schema
- 금지 action
- 검증 실패 feedback
- JSON 출력 형식

Planner는 자연어 action을 내지 않고 다음 같은 구조를 생성한다.

```json
[
  {
    "building_id": "Building_10",
    "action": -0.35,
    "mode": "discharge",
    "reason": "SOC is sufficient and net load is high.",
    "expected_effect": "Reduce district peak.",
    "confidence": 0.78
  }
]
```

## 10. 우선 구현 순서

1. LLM 없는 deterministic Grid-Agent MVP를 만든다.
2. `TopologyAnalyzer`, `ViolationDetector`, `SandboxExecutor`, `ConstraintValidator`를 구현한다.
3. `/citylearn/grid-agent/plan` endpoint를 추가한다.
4. Board에 action/validation panel을 붙인다.
5. 이후 `tool_catalog.py`에 validation MCP tool을 추가해 LLM Planner를 연결한다.
6. 마지막에 run/action 로그 테이블과 KPI 비교 리포트를 만든다.

## 11. 최종 목표

MeshBoard의 Grid-Agent는 "LLM이 도시 전력망을 직접 제어하는 시스템"이 아니다.

목표는 **Agent-Mesh가 제안한 도시 에너지 제어 전략을 sandbox로 검증하고, 운영자가 승인 가능한 설명과 KPI 근거를 제공하는 제어 보조 시스템**이다.

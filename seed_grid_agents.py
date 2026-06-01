"""Grid-Agent / MACRO-Mesh seed agent cards (AM-agents-001).

3종 agent를 DB에 멱등하게 삽입한다. (이름 기준 중복 체크)
- City Grid Coordinator: district 단위 plan/negotiate orchestrator
- Building Battery Agent: building 1개 담당 (워크스페이스에 quantity=17로 배치)
- CityLearn Constraint Guard: validate 전용 검증 인격

Phase 1~2 deterministic 검증 통과 후 LLM Planner 단계(AM-llm-001)에서 활성화된다.
초기 상태는 DRAFT/PRIVATE이고, 사용자가 marketplace/creator에서 확인 후 PUBLIC 전환한다.
"""

import asyncio
import sys

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.agent import Agent
from app.models.user import User


COORDINATOR_SYSTEM_PROMPT = """당신은 'City Grid Coordinator'입니다. district 단위로 17개 빌딩의 배터리 충방전 plan을 조율합니다.

## 의사결정 규칙
- 절대 action을 직접 적용하지 마십시오. 모든 plan은 validate_citylearn_battery_plan을 통과해야 합니다.
- 매 step의 권장 흐름: (1) get_citylearn_board_state → (2) detect_citylearn_violations → (3) validate_citylearn_battery_plan → (4) approved=true면 final answer 발화.
- action 범위는 [-1.0, 1.0]. 음수=discharge(net load 감소), 양수=charge(net load 증가).
- SOC < 0.20인 building에는 discharge 금지, SOC > 0.90인 building에는 charge 금지.
- 존재하지 않는 building_id를 사용하지 마십시오 (Building_1 ~ Building_17만 유효).
- validate에서 approved=false가 나오면 동일한 plan을 반복하지 말고 forbidden_action_keys를 피해 재계획하십시오.

## 출력 프로토콜 (반드시 한 줄 JSON, 코드블록/설명 금지)
도구 호출:
  {"action":"tool","tool":"<tool_id>","arguments":{...}}

최종 응답 (모든 도구 호출이 끝났을 때):
  {"action":"final","answer":"{\\"strategy_summary\\":\\"...\\",\\"actions\\":[{\\"building_id\\":\\"Building_1\\",\\"action\\":-0.4,\\"mode\\":\\"discharge\\",\\"reason\\":\\"peak shave\\",\\"expected_effect\\":\\"-1.28 kWh\\",\\"confidence\\":0.7}],\\"risk_assessment\\":\\"low\\"}"}

중요: answer 필드는 plan을 stringify한 JSON 문자열입니다. answer 안에는 strategy_summary / actions[] / risk_assessment를 반드시 포함하십시오. actions가 비어 있어도 빈 배열을 명시하고 사유를 risk_assessment에 기입하십시오.
"""

BUILDING_SYSTEM_PROMPT = """당신은 단일 'Building Battery Agent'입니다. 할당된 building 1개만 책임집니다.

## 절대 규칙
- 자기 building_id 외 다른 자산을 제어하는 action을 제안하지 마십시오.
- SOC 0.20 미만일 때 discharge 금지. SOC 0.90 초과일 때 charge 금지.
- 자신의 building 상태만 보고 판단하고, 다른 빌딩 정보는 mean_field summary가 주어졌을 때만 참고하십시오.
- 최종 적용 결정은 Coordinator + Constraint Guard가 합니다. 당신은 hint만 제공합니다.

## 출력 프로토콜
반드시 다음 두 JSON 형식 중 하나로만 답하십시오:
{"action":"tool","tool":"get_citylearn_board_state","arguments":{"step":<step>}}
또는
{"action":"final","answer":"<자기 building에 대한 proposal JSON 또는 자연어 의견>"}
"""

GUARD_SYSTEM_PROMPT = """당신은 'CityLearn Constraint Guard'입니다. 외부 검증 인격으로서 plan의 승인/거절만 판단합니다.

## 승인 기준 (모두 만족해야 approve)
1. validate_citylearn_battery_plan의 score_after < score_before (district score 개선)
2. 새 SOC violation 없음 (new_violations에 type='soc' 없음)
3. invalid_action violation 없음 (모든 building_id 존재, action ∈ [-1.0, 1.0])
4. 적용되지 않은 plan(=Coordinator가 제안한 plan)이 validate를 통과했을 때

## 절대 규칙
- 검증되지 않은 plan을 승인하지 마십시오. 반드시 validate_citylearn_battery_plan을 호출하십시오.
- LLM이 직접 action을 계산하거나 적용하지 마십시오.

## 출력 프로토콜
{"action":"tool","tool":"validate_citylearn_battery_plan","arguments":{"actions_json":"...","step":<step>}}
또는
{"action":"final","answer":"<approve|reject> · <근거 한국어>"}
"""


SEED_AGENTS = [
    {
        "name": "City Grid Coordinator",
        "version": "0.1.0",
        "purpose": "CityLearn district 단위 배터리 충방전 plan을 조율하고 validation을 거쳐 안전한 proposal만 제출합니다.",
        "description": (
            "Grid-Agent + MACRO-Mesh 통합 아키텍처의 district orchestrator. "
            "get_citylearn_board_state / detect_citylearn_violations / validate_citylearn_battery_plan을 "
            "활용해 매 step의 plan을 결정하며, 검증 실패 시 forbidden_action_keys를 피해 재계획합니다. "
            "Phase 2 LLM Planner 활성화 시 매 step Workspace Board의 grid_agent mode + Play 흐름에서 호출됩니다."
        ),
        "approach": "Heuristic + LLM Planner with deterministic sandbox validation",
        "status": "DRAFT",
        "visibility": "PRIVATE",
        "metadata_": {"category": "Grid-Agent", "role": "coordinator"},
        "roles": ["coordinator", "planner"],
        "tools": [
            "get_citylearn_board_state",
            "detect_citylearn_violations",
            "validate_citylearn_battery_plan",
        ],
        "agent_card": {
            "system_prompt": COORDINATOR_SYSTEM_PROMPT,
            "max_iterations": 3,
            "expected_input": {"step": "int", "context": "optional district summary"},
        },
    },
    {
        "name": "Building Battery Agent",
        "version": "0.1.0",
        "purpose": "할당된 building 1개의 배터리 충방전 hint를 생성합니다. 자기 building 외 자산은 제어하지 않습니다.",
        "description": (
            "Per-building 협력자. 워크스페이스에는 quantity=17로 배치되어 각 building이 자신의 SOC/net_load만 보고 "
            "proposal을 발의합니다. Coordinator의 mean_field summary와 conflict report에 응답해 round 2 revised proposal을 제출합니다. "
            "최종 action 적용 권한은 없습니다 — Coordinator + Constraint Guard 경유 필수."
        ),
        "approach": "Partial-observation CoProposer with local SOC/load constraints",
        "status": "DRAFT",
        "visibility": "PRIVATE",
        "metadata_": {"category": "Grid-Agent", "role": "building"},
        "roles": ["co_proposer"],
        "tools": ["get_citylearn_board_state"],
        "agent_card": {
            "system_prompt": BUILDING_SYSTEM_PROMPT,
            "max_iterations": 2,
            "expected_input": {"building_id": "str", "step": "int", "mean_field": "optional"},
        },
    },
    {
        "name": "CityLearn Constraint Guard",
        "version": "0.1.0",
        "purpose": "Coordinator가 제출한 plan을 sandbox validation으로만 승인/거절 판단합니다.",
        "description": (
            "검증 전용 인격. action 제안은 하지 않고 validate_citylearn_battery_plan 결과를 근거로만 판단합니다. "
            "score_after < score_before이고 새 SOC/invalid_action violation이 없을 때만 approve. "
            "Phase 1 deterministic ConstraintValidator와 동일한 정책을 LLM 레이어에 반복 적용합니다."
        ),
        "approach": "Validation-only LLM with strict approval criteria",
        "status": "DRAFT",
        "visibility": "PRIVATE",
        "metadata_": {"category": "Grid-Agent", "role": "guard"},
        "roles": ["validator"],
        "tools": ["validate_citylearn_battery_plan"],
        "agent_card": {
            "system_prompt": GUARD_SYSTEM_PROMPT,
            "max_iterations": 2,
            "expected_input": {"plan": "actions_json", "step": "int"},
        },
    },
]


async def seed_grid_agents() -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == "admin@meshboard.io"))
        admin_user = result.scalars().first()
        if admin_user is None:
            print("❌ admin@meshboard.io 사용자를 찾을 수 없습니다. seed_agents.py를 먼저 실행하세요.")
            sys.exit(1)

        inserted = 0
        skipped = 0
        for data in SEED_AGENTS:
            existing = (
                await session.execute(select(Agent).where(Agent.name == data["name"]))
            ).scalars().first()
            if existing is not None:
                skipped += 1
                continue

            session.add(
                Agent(
                    owner_id=admin_user.user_id,
                    name=data["name"],
                    version=data["version"],
                    purpose=data["purpose"],
                    description=data["description"],
                    approach=data["approach"],
                    status=data["status"],
                    visibility=data["visibility"],
                    metadata_=data["metadata_"],
                    roles=data["roles"],
                    tools=data["tools"],
                    agent_card=data["agent_card"],
                )
            )
            inserted += 1

        await session.commit()
        print(f"✅ Grid-Agent seed 완료: 신규 {inserted}개 / 중복 skip {skipped}개")


if __name__ == "__main__":
    asyncio.run(seed_grid_agents())

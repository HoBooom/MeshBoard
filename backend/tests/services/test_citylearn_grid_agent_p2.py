"""P2 통합 verification: MCP tools + Coordinator seed + LLM Planner fallback (AM-mcp-001/AM-agents-001/AM-llm-001)."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.tool_catalog import TOOL_REGISTRY, list_tool_descriptors


class GridAgentMcpToolsTests(unittest.TestCase):
    """AM-mcp-001 verification: tool registry + 출력 shape + 거절 경로."""

    def test_v1_tools_registered_and_listed(self) -> None:
        ids = {d["id"] for d in list_tool_descriptors()}
        for tool_id in [
            "get_citylearn_board_state",
            "detect_citylearn_violations",
            "validate_citylearn_battery_plan",
        ]:
            self.assertIn(tool_id, TOOL_REGISTRY)
            self.assertIn(tool_id, ids)

    def test_v2_validate_rejects_invalid_json(self) -> None:
        raw = TOOL_REGISTRY["validate_citylearn_battery_plan"].invoke({"actions_json": "not json"})
        parsed = json.loads(raw)
        self.assertFalse(parsed["approved"])
        self.assertIn("JSON 파싱 실패", parsed["feedback"])

    def test_v3_validate_rejects_unknown_building(self) -> None:
        actions = json.dumps([{
            "building_id": "Building_999",
            "action": -0.3,
            "mode": "discharge",
            "reason": "test",
            "expected_effect": "test",
            "confidence": 0.5,
        }])
        raw = TOOL_REGISTRY["validate_citylearn_battery_plan"].invoke({"actions_json": actions, "step": 100})
        parsed = json.loads(raw)
        self.assertFalse(parsed["approved"])
        types = {v["type"] for v in parsed.get("new_violations", [])}
        self.assertIn("invalid_action", types)

    def test_v4_get_board_state_includes_17_buildings(self) -> None:
        raw = TOOL_REGISTRY["get_citylearn_board_state"].invoke({"step": 100})
        parsed = json.loads(raw)
        self.assertEqual(parsed["building_count"], 17)
        self.assertEqual(len(parsed["buildings"]), 17)
        # mapping violation은 권한 컨텍스트에서만 — get_state는 mapping 없이도 동작.
        for b in parsed["buildings"]:
            self.assertIn("battery_soc", b)
            self.assertIn("net_load_kwh", b)


class GridAgentSeedTests(unittest.TestCase):
    """AM-agents-001 verification: SEED_AGENTS 정의 검증."""

    def test_v1_three_seed_agents_defined(self) -> None:
        from seed_grid_agents import SEED_AGENTS
        names = [a["name"] for a in SEED_AGENTS]
        self.assertIn("City Grid Coordinator", names)
        self.assertIn("Building Battery Agent", names)
        self.assertIn("CityLearn Constraint Guard", names)

    def test_v2_coordinator_has_validate_tool(self) -> None:
        from seed_grid_agents import SEED_AGENTS
        coordinator = next(a for a in SEED_AGENTS if a["name"] == "City Grid Coordinator")
        self.assertIn("validate_citylearn_battery_plan", coordinator["tools"])
        self.assertIn("get_citylearn_board_state", coordinator["tools"])
        self.assertIn("detect_citylearn_violations", coordinator["tools"])

    def test_v3_building_agent_prompt_restricts_to_own_building(self) -> None:
        from seed_grid_agents import SEED_AGENTS
        building = next(a for a in SEED_AGENTS if a["name"] == "Building Battery Agent")
        prompt = building["agent_card"]["system_prompt"]
        self.assertIn("building_id", prompt)
        self.assertIn("자기 building_id 외 다른 자산을 제어하는 action을 제안하지 마십시오", prompt)

    def test_v4_guard_prompt_states_approval_criteria(self) -> None:
        from seed_grid_agents import SEED_AGENTS
        guard = next(a for a in SEED_AGENTS if a["name"] == "CityLearn Constraint Guard")
        prompt = guard["agent_card"]["system_prompt"]
        self.assertIn("score_after < score_before", prompt)
        self.assertIn("SOC violation 없음", prompt)
        self.assertIn("invalid_action violation 없음", prompt)


class GridAgentLLMPlannerTests(unittest.TestCase):
    """AM-llm-001 verification: fallback + schema 파서."""

    def test_v1_fallback_returns_heuristic_iteration_when_no_db(self) -> None:
        from uuid import uuid4
        from app.services.citylearn_board import get_board_snapshot
        from app.services.citylearn_grid_agent_llm import run_llm_planner_loop

        snapshot = get_board_snapshot(
            step=120, baseline_model="basic_rbc", agent_mesh_mode="grid_agent", window=24,
        )
        result = asyncio.run(run_llm_planner_loop(
            db=None,
            workspace_id=uuid4(),
            snapshot=snapshot,
            mapping=None,
            baseline_model="basic_rbc",
            agent_mesh_mode="grid_agent",
            max_iterations=3,
        ))
        self.assertEqual(len(result.iterations), 1)
        self.assertEqual(result.iterations[0].planner_kind, "heuristic")
        self.assertIn("fallback", result.iterations[0].route_decision or "")
        self.assertIsNotNone(result.final_plan)

    def test_v2_parse_llm_plan_accepts_valid_json(self) -> None:
        from app.services.citylearn_grid_agent_llm import _parse_llm_plan
        raw = json.dumps({
            "strategy_summary": "shave",
            "actions": [
                {
                    "building_id": "Building_1", "action": -0.4, "mode": "discharge",
                    "reason": "peak", "expected_effect": "-1.28 kWh", "confidence": 0.7,
                }
            ],
            "risk_assessment": "low",
        })
        plan = _parse_llm_plan(raw, valid_building_ids={"Building_1", "Building_2"})
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].building_id, "Building_1")

    def test_v3_parse_llm_plan_rejects_unknown_building(self) -> None:
        from app.services.citylearn_grid_agent_llm import _parse_llm_plan
        raw = json.dumps({
            "strategy_summary": "x",
            "actions": [{"building_id": "Building_999", "action": 0.5, "mode": "charge",
                         "reason": "r", "expected_effect": "e", "confidence": 0.5}],
            "risk_assessment": "x",
        })
        plan = _parse_llm_plan(raw, valid_building_ids={"Building_1", "Building_2"})
        self.assertIsNone(plan)

    def test_v4_parse_llm_plan_rejects_out_of_range_action(self) -> None:
        from app.services.citylearn_grid_agent_llm import _parse_llm_plan
        raw = json.dumps({
            "strategy_summary": "x",
            "actions": [{"building_id": "Building_1", "action": 1.5, "mode": "charge",
                         "reason": "r", "expected_effect": "e", "confidence": 0.5}],
            "risk_assessment": "x",
        })
        plan = _parse_llm_plan(raw, valid_building_ids={"Building_1"})
        self.assertIsNone(plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)

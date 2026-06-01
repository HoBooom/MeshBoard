"""Grid-Agent deterministic 엔진 verification suite (AM-engine-001).

각 테스트는 feature_list.json의 verification 항목과 1:1 매핑된다.
의도적으로 stdlib unittest만 사용 — 백엔드는 현재 pytest 의존성을 두지 않는다.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

# 백엔드 루트(backend/)를 PYTHONPATH에 추가하여 `app.*` import를 가능하게 한다.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.citylearn_grid_agent import (
    CityLearnAction,
    CityLearnPlan,
    TopologySummary,
)
from app.services import citylearn_board
from app.services.citylearn_grid_agent import (
    ConstraintValidator,
    HeuristicPlanner,
    SandboxExecutor,
    TopologyAnalyzer,
    ViolationDetector,
    run_deterministic_plan,
)
from app.services.citylearn_grid_agent_constants import (
    SOC_HARD_LOWER,
    SOC_SOFT_LOWER,
)


def _make_mapping(building_ids: List[str], *, unmapped: List[str] = ()) -> Dict[str, Any]:
    """workspace metadata 형태의 agent_building_mapping payload."""
    agent_id = str(uuid4())
    return {
        "agent_building_mapping": {
            "central_controller_agents": [
                {"agent_id": agent_id, "agent_name": "City Grid Coordinator"}
            ],
            "buildings": [
                {
                    "building_id": bid,
                    "assigned_agent_id": None if bid in unmapped else str(uuid4()),
                    "assigned_agent_name": None if bid in unmapped else "Building Battery Agent",
                }
                for bid in building_ids
            ],
        }
    }


def _make_synthetic_snapshot(
    *,
    step: int = 100,
    buildings_spec: List[Dict[str, Any]],
    district_prev: float = 30.0,
) -> Dict[str, Any]:
    """테스트 격리를 위한 deterministic snapshot factory."""
    buildings = [
        {
            "building_id": spec["building_id"],
            "battery_soc": spec.get("battery_soc", 0.5),
            "agent_mesh_net_load_kwh": spec.get("net_load_kwh", 3.0),
            "net_load_kwh": spec.get("net_load_kwh", 3.0),
            "pv_generation_kwh": spec.get("pv_generation_kwh", 0.5),
            "current_consumption_kwh": spec.get("net_load_kwh", 3.0) + 0.5,
            "baseline_net_load_kwh": spec.get("net_load_kwh", 3.0) + 1.0,
            "battery_action": "idle",
            "agent_intervention": False,
            "agent_action_description": None,
            "history": [],
        }
        for spec in buildings_spec
    ]
    current_district = sum(b["agent_mesh_net_load_kwh"] for b in buildings)
    points = [
        {"time_step": step - 1, "time_label": f"T+{step-1}", "baseline": district_prev,
         "agent_mesh": district_prev, "baseline_reward": 0.0, "agent_mesh_reward": 0.0},
        {"time_step": step, "time_label": f"T+{step}", "baseline": current_district,
         "agent_mesh": current_district, "baseline_reward": 0.0, "agent_mesh_reward": 0.0},
    ]
    return {
        "dataset": {"id": "test", "path": "test", "total_steps": 8760, "central_agent": False, "active_actions": []},
        "runtime": {
            "citylearn_data_connected": True,
            "citylearn_environment_step_connected": False,
            "baseline_runner_connected": False,
            "agent_mesh_action_api_connected": False,
            "source": "synthetic_test",
        },
        "step": step,
        "points": points,
        "buildings": buildings,
        "baseline_model": "basic_rbc",
        "agent_mesh_mode": "demo_heuristic",
    }


class TopologyAndMappingTests(unittest.TestCase):
    """v1: topology_summary에 controllable_assets 17개 / v2: mapping violation."""

    def test_v1_topology_includes_17_controllable_assets_from_real_dataset(self) -> None:
        snapshot = citylearn_board.get_board_snapshot(
            step=120, baseline_model="basic_rbc", agent_mesh_mode="demo_heuristic", window=24,
        )
        building_ids = [b["building_id"] for b in snapshot["buildings"]]
        mapping = _make_mapping(building_ids)

        topology = TopologyAnalyzer().analyze(
            workspace_id=uuid4(), snapshot=snapshot, mapping=mapping,
        )

        self.assertEqual(len(topology.controllable_assets), 17,
                         "phase_all 데이터셋은 17개 빌딩을 가져야 한다.")
        self.assertEqual(topology.mapped_building_count, 17)
        self.assertIsInstance(topology, TopologySummary)

    def test_v2_unmapped_building_creates_mapping_violation(self) -> None:
        snapshot = _make_synthetic_snapshot(buildings_spec=[
            {"building_id": "Building_1", "battery_soc": 0.5, "net_load_kwh": 3.0},
            {"building_id": "Building_2", "battery_soc": 0.6, "net_load_kwh": 2.0},
        ])
        mapping = _make_mapping(["Building_1", "Building_2"], unmapped=["Building_2"])

        topology = TopologyAnalyzer().analyze(
            workspace_id=uuid4(), snapshot=snapshot, mapping=mapping,
        )
        violations = ViolationDetector().detect_initial(topology=topology, snapshot=snapshot)

        mapping_violations = [v for v in violations if v.type == "mapping"]
        self.assertEqual(len(mapping_violations), 1)
        self.assertEqual(mapping_violations[0].building_id, "Building_2")
        self.assertEqual(topology.mapped_building_count, 1)


class HeuristicPlannerTests(unittest.TestCase):
    """v3: SOC < 0.20인 building에는 discharge action이 생성되지 않는다."""

    def test_v3_low_soc_building_never_receives_discharge_action(self) -> None:
        snapshot = _make_synthetic_snapshot(buildings_spec=[
            {"building_id": "Building_1", "battery_soc": 0.10, "net_load_kwh": 8.0},  # 매우 낮은 SOC + 고부하
            {"building_id": "Building_2", "battery_soc": 0.50, "net_load_kwh": 6.0},
        ])
        mapping = _make_mapping(["Building_1", "Building_2"])

        topology = TopologyAnalyzer().analyze(
            workspace_id=uuid4(), snapshot=snapshot, mapping=mapping,
        )
        violations = ViolationDetector().detect_initial(topology=topology, snapshot=snapshot)
        plan = HeuristicPlanner().propose(topology=topology, violations=violations)

        low_soc_actions = [a for a in plan.actions if a.building_id == "Building_1"]
        # SOC < SOC_SOFT_LOWER 인 빌딩은 discharge 후보에서 항상 제외되어야 한다.
        for action in low_soc_actions:
            self.assertNotEqual(action.mode, "discharge",
                                f"SOC<{SOC_SOFT_LOWER} 빌딩에 discharge 발생: {action}")
        # 추가로 SOC 하한 violation이 검출되어야 한다.
        soc_violations = [v for v in violations if v.type == "soc"]
        self.assertTrue(any(v.building_id == "Building_1" for v in soc_violations))


class SandboxIsolationTests(unittest.TestCase):
    """v4: sandbox 실행 후 원본 snapshot 객체가 변경되지 않는다."""

    def test_v4_sandbox_does_not_mutate_original_snapshot(self) -> None:
        snapshot = _make_synthetic_snapshot(buildings_spec=[
            {"building_id": "Building_1", "battery_soc": 0.6, "net_load_kwh": 6.0},
            {"building_id": "Building_2", "battery_soc": 0.7, "net_load_kwh": 5.0},
        ])
        snapshot_signature = copy.deepcopy(snapshot)

        plan = CityLearnPlan(
            strategy_summary="test", risk_assessment="test",
            actions=[
                CityLearnAction(
                    building_id="Building_1", action=-0.5, mode="discharge",
                    reason="test", expected_effect="test", confidence=0.7,
                ),
                CityLearnAction(
                    building_id="Building_2", action=0.4, mode="charge",
                    reason="test", expected_effect="test", confidence=0.7,
                ),
            ],
        )
        sandbox = SandboxExecutor().execute(snapshot=snapshot, plan=plan)

        # 원본은 deep-equal하게 보존되어야 한다.
        self.assertEqual(snapshot, snapshot_signature, "원본 snapshot이 변경되었다.")
        # sandbox는 변경이 반영되어야 한다.
        sandbox_b1 = next(b for b in sandbox["buildings"] if b["building_id"] == "Building_1")
        self.assertLess(sandbox_b1["agent_mesh_net_load_kwh"], 6.0)
        self.assertLess(sandbox_b1["battery_soc"], 0.6)
        sandbox_b2 = next(b for b in sandbox["buildings"] if b["building_id"] == "Building_2")
        self.assertGreater(sandbox_b2["agent_mesh_net_load_kwh"], 5.0)
        self.assertGreater(sandbox_b2["battery_soc"], 0.7)


class ConstraintValidatorTests(unittest.TestCase):
    """v5: score_after가 score_before보다 나쁘면 approved=false."""

    def test_v5_worse_score_after_yields_rejected(self) -> None:
        snapshot = _make_synthetic_snapshot(
            step=200,
            district_prev=20.0,
            buildings_spec=[
                {"building_id": "Building_1", "battery_soc": 0.45, "net_load_kwh": 2.0},
                {"building_id": "Building_2", "battery_soc": 0.55, "net_load_kwh": 2.5},
            ],
        )
        mapping = _make_mapping(["Building_1", "Building_2"])

        # 일부러 score를 악화시키는 plan: 저부하 빌딩에 강한 charge → district load 증가.
        plan = CityLearnPlan(
            strategy_summary="intentionally bad",
            risk_assessment="should be rejected",
            actions=[
                CityLearnAction(
                    building_id="Building_1", action=1.0, mode="charge",
                    reason="force load up", expected_effect="net load 증가", confidence=0.1,
                ),
                CityLearnAction(
                    building_id="Building_2", action=1.0, mode="charge",
                    reason="force load up", expected_effect="net load 증가", confidence=0.1,
                ),
            ],
        )

        analyzer = TopologyAnalyzer()
        topology_before = analyzer.analyze(workspace_id=uuid4(), snapshot=snapshot, mapping=mapping)
        initial_violations = ViolationDetector().detect_initial(topology=topology_before, snapshot=snapshot)
        sandbox = SandboxExecutor().execute(snapshot=snapshot, plan=plan)
        topology_after = analyzer.analyze(workspace_id=uuid4(), snapshot=sandbox, mapping=mapping)

        result = ConstraintValidator().validate(
            snapshot_before=snapshot,
            snapshot_after=sandbox,
            topology_before=topology_before,
            topology_after=topology_after,
            plan=plan,
            initial_violations=initial_violations,
        )

        self.assertGreaterEqual(result.score_after, result.score_before)
        self.assertFalse(result.approved)
        self.assertEqual(result.status, "rejected")
        # forbidden_action_keys에 거절된 plan의 키들이 누적되어야 한다.
        self.assertTrue(any("Building_1:1.00" in k for k in result.forbidden_action_keys))


class OrchestrationSmokeTest(unittest.TestCase):
    """run_deterministic_plan 통합 호출이 발의/검증/요약을 한 번에 produce하는지 확인."""

    def test_orchestrator_returns_plan_validation_and_summary(self) -> None:
        snapshot = _make_synthetic_snapshot(buildings_spec=[
            {"building_id": "Building_1", "battery_soc": 0.85, "net_load_kwh": 6.5},
            {"building_id": "Building_2", "battery_soc": 0.30, "net_load_kwh": 1.0},
            {"building_id": "Building_3", "battery_soc": SOC_HARD_LOWER - 0.02, "net_load_kwh": 4.0},
        ])
        mapping = _make_mapping(["Building_1", "Building_2", "Building_3"])

        result = run_deterministic_plan(
            workspace_id=uuid4(), snapshot=snapshot, mapping=mapping,
        )

        self.assertEqual(result.topology.building_count, 3)
        self.assertIsNotNone(result.operator_summary)
        self.assertIn("Grid-Agent", result.operator_summary)
        self.assertIsInstance(result.final_plan, CityLearnPlan)
        # 낮은 SOC 빌딩은 discharge되지 않았어야 한다.
        b3_discharge = [a for a in result.final_plan.actions
                        if a.building_id == "Building_3" and a.mode == "discharge"]
        self.assertEqual(b3_discharge, [], "SOC 하한 빌딩에 discharge가 생성되었다.")


if __name__ == "__main__":
    unittest.main(verbosity=2)

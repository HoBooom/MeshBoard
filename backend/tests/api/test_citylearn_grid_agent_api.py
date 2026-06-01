"""Grid-Agent API verification (AM-api-001).

FastAPI TestClient + dependency_overrides로 DB/auth를 격리하고,
실제 deterministic 엔진과 board snapshot은 진짜를 사용한다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.v1 import citylearn as citylearn_module
from app.core.security import get_current_user
from app.db.session import get_db
from app.main import app


def _make_user(user_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, roles=["agent_engineer"], state="ACTIVE")


def _make_workspace(workspace_id: UUID, *, with_mapping: bool) -> SimpleNamespace:
    mapping = {
        "agent_building_mapping": {
            "central_controller_agents": [
                {"agent_id": str(uuid4()), "agent_name": "City Grid Coordinator"}
            ],
            "buildings": [
                {
                    "building_id": f"Building_{i}",
                    "assigned_agent_id": str(uuid4()) if with_mapping else None,
                    "assigned_agent_name": "Building Battery Agent" if with_mapping else None,
                }
                for i in range(1, 18)
            ],
        }
    }
    return SimpleNamespace(workspace_id=workspace_id, metadata_=mapping)


class GridAgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_id = uuid4()
        self.workspace_id = uuid4()

        async def _noop_db():
            yield None  # endpoint는 _ensure_access를 monkey patch하므로 실제 DB 미사용

        async def _stub_current_user():
            return _make_user(self.user_id)

        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _stub_current_user

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    # ── helpers ────────────────────────────────────────────────

    def _patch_ensure_access(self, *, allow: bool, with_mapping: bool = True):
        workspace = _make_workspace(self.workspace_id, with_mapping=with_mapping)

        async def _allow_access(db, workspace_id, user):
            return workspace

        async def _deny_access(db, workspace_id, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="워크스페이스 접근 권한이 없습니다.",
            )

        return patch.object(
            citylearn_module, "_ensure_access",
            _allow_access if allow else _deny_access,
        )

    # ── tests ──────────────────────────────────────────────────

    def test_v1_analyze_authorized_user_returns_200(self) -> None:
        with self._patch_ensure_access(allow=True):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/analyze",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 120,
                    "baseline_model": "basic_rbc",
                    "agent_mesh_mode": "demo_heuristic",
                    "window": 24,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("run_id", body)
        self.assertIn("topology", body)
        self.assertIn("initial_violations", body)
        self.assertEqual(len(body["topology"]["controllable_assets"]), 17)

    def test_v2_unauthorized_workspace_returns_403(self) -> None:
        with self._patch_ensure_access(allow=False):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/analyze",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 120,
                    "baseline_model": "basic_rbc",
                    "agent_mesh_mode": "demo_heuristic",
                    "window": 24,
                },
            )
        self.assertEqual(response.status_code, 403, response.text)

    def test_v3_plan_response_has_required_fields(self) -> None:
        with self._patch_ensure_access(allow=True):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/plan",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 200,
                    "baseline_model": "basic_rbc",
                    "agent_mesh_mode": "demo_heuristic",
                    "window": 24,
                    "max_iterations": 1,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        for field in ("run_id", "initial_violations", "final_plan", "validation", "operator_summary"):
            self.assertIn(field, body, f"필수 응답 필드 누락: {field}")
        self.assertIn("approved", body["validation"])
        self.assertIn("score_before", body["validation"])
        self.assertIn("score_after", body["validation"])
        self.assertEqual(len(body["iterations"]), 1)
        self.assertEqual(body["iterations"][0]["planner_kind"], "heuristic")

    def test_v4_existing_board_endpoint_still_works(self) -> None:
        response = self.client.get(
            "/api/v1/citylearn/board",
            params={
                "step": 100,
                "baseline_model": "basic_rbc",
                "agent_mesh_mode": "demo_heuristic",
                "window": 24,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("buildings", body)
        self.assertEqual(len(body["buildings"]), 17)

    def test_bonus_mapping_violation_surfaces_through_api(self) -> None:
        """metadata에 unassigned building이 있으면 응답에 mapping violation이 포함된다."""
        with self._patch_ensure_access(allow=True, with_mapping=False):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/analyze",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 50,
                    "baseline_model": "basic_rbc",
                    "agent_mesh_mode": "demo_heuristic",
                    "window": 24,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        mapping_violations = [v for v in body["initial_violations"] if v["type"] == "mapping"]
        self.assertEqual(len(mapping_violations), 17)

    def test_bonus_llm_planner_falls_back_to_heuristic_when_agent_not_seeded(self) -> None:
        """AM-llm-001: db=None(테스트 환경) 또는 coordinator agent 미시드 시 heuristic fallback.

        Phase 2에서는 LLM Planner를 거절하지 않고, agent 부재/LLM 호출 실패를 fallback iteration으로 trace한다.
        """
        with self._patch_ensure_access(allow=True):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/plan",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 50,
                    "use_llm_planner": True,
                    "max_iterations": 1,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["iterations"]), 1)
        self.assertEqual(body["iterations"][0]["planner_kind"], "heuristic")
        self.assertIn("fallback", body["iterations"][0]["route_decision"])

    def test_bonus_grid_agent_mode_literal_accepted_by_plan(self) -> None:
        """AM-ui-001: agent_mesh_mode='grid_agent' literal이 plan API에서 200으로 통과한다."""
        with self._patch_ensure_access(allow=True):
            response = self.client.post(
                "/api/v1/citylearn/grid-agent/plan",
                json={
                    "workspace_id": str(self.workspace_id),
                    "step": 300,
                    "baseline_model": "basic_rbc",
                    "agent_mesh_mode": "grid_agent",
                    "window": 24,
                    "max_iterations": 1,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["topology"]["agent_mesh_mode"], "grid_agent")
        self.assertEqual(len(body["topology"]["controllable_assets"]), 17)

    def test_bonus_invalid_payload_returns_422(self) -> None:
        response = self.client.post(
            "/api/v1/citylearn/grid-agent/plan",
            json={
                "workspace_id": str(self.workspace_id),
                "step": 9999,  # > 8759
            },
        )
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

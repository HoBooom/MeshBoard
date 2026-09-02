"""MESH-CHESCA runtime bridge for the city-management board (mesh_chesca template).

Wraps the teammate's CHESCA-vs-Mesh experiment (Final_mesh1-main) as an incremental,
step-by-step rollout so the existing CityLearn board UI can be reused for a new
"도시관리 mesh_chesca" workspace template.

Design (mirrors citylearn_sacrbc_inference.py):
- Heavy imports (vendored CityLearn 2.1b12 + checa + xgboost) are lazy so the API still
  serves other workspaces when these optional deps are missing.
- One MeshChescaRunner per (dataset, scenario). Each builds a CityLearn env + a CHESCA
  controller and steps it incrementally, caching a per-step record.
- Per step we capture: realized per-building state from the env (net load / soc / pv) plus
  the controller's mesh negotiation trace (message_log = FlexBroadcast per peer/round,
  negotiation_log = NegotiationOutcome per step) so the board can show official vs
  negotiated district load and the peer flexibility messages.

Scenarios (chosen by the user):
- chesca_official        : official CHESCA SubmissionAgent (no mesh negotiation)
- chesca_mesh            : MeshCheca (P2P flex negotiation around the official action)
- reserve_contract_mesh  : ReserveContractMeshCheca (respects CHESCA outage reserve)
- commitment_mesh        : CommitmentMeshCheca (discharge debt / budget ledger)
- round_robin_commitment : RoundRobinCommitmentMeshCheca (rotating planner ownership)
"""

from __future__ import annotations

# NOTE: 이 모듈은 반드시 mesh_chesca_worker 서브프로세스 안에서만 "실행"된다.
# (vendored CityLearn 2.1b12가 top-level 'citylearn' 패키지명을 점유해, 메인 API 프로세스의
#  SACRBC용 CityLearn_old_system과 충돌하기 때문. worker가 OMP_NUM_THREADS=1을 미리 설정한다.)
# 메인 프로세스는 SCENARIOS/available_datasets 같은 상수/파일목록만 import 한다(citylearn 미적재).

import math
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHESCA_ROOT = PROJECT_ROOT / "Final_mesh1-main"
CHESCA_SRC = CHESCA_ROOT / "src"
CITYLEARN_VENDOR = CHESCA_ROOT / "third_party" / "CityLearn-2.1b12"
OFFICIAL_ROOT = CHESCA_ROOT / "CHESCA-main"
SCHEMA_ROOT = OFFICIAL_ROOT / "data" / "schemas"

DEFAULT_DATASET = "citylearn_challenge_2023_phase_3_1"

# scenario id -> human label + which controller class drives it.
SCENARIOS: Dict[str, Dict[str, str]] = {
    "chesca_official": {
        "label": "CHESCA Official (baseline)",
        "kind": "official",
        "description": "공식 CHESCA SubmissionAgent. mesh 협상 없이 건물별 배터리 tree-search만 수행.",
    },
    "chesca_mesh": {
        "label": "CHESCA + Mesh",
        "kind": "mesh",
        "description": "공식 CHESCA action을 outside option으로 두고 peer 간 flex offer를 주고받아 district 부하를 협상.",
    },
    "reserve_contract_mesh": {
        "label": "Reserve Contract Mesh",
        "kind": "reserve",
        "description": "CHESCA의 outage reserve(min-SOC)를 침범하지 않는 범위에서만 협상해 resilience를 보존.",
    },
    "commitment_mesh": {
        "label": "Commitment Mesh",
        "kind": "commitment",
        "description": "과방전 debt/budget ledger를 추적해 과도한 동시 방전을 억제.",
    },
    "round_robin_commitment": {
        "label": "Round-Robin Coordinator",
        "kind": "round_robin",
        "description": "commitment 로직 + planner 소유권을 라운드로빈으로 회전시키는 분산 coordinator 프로토콜.",
    },
    # 외부 런타임 시나리오: 이 CHESCA 워커(vendored CityLearn 2.1b12)에서 구동하지 않는다.
    # research/agent_mesh.ipynb 모델(OpenSynCity 정전 MPC mesh)을 CityLearn_old_system(2.6.0b2,
    # 2022 phase_all + 정전 주입)에서 메인 프로세스 in-process로 구동하며, API 레이어가
    # app.services.agent_mesh_runtime 로 라우팅한다. 여기엔 dropdown/검증용으로만 등록한다.
    "outage_mpc_mesh": {
        "label": "OpenSynCity 정전 MPC Mesh",
        "kind": "external_outage_mpc",
        "description": "에이전틱 메시 + 배터리 MPC(LP) + 정전 회복력. 저녁 피크 정전 주입 환경에서 "
        "OutageRiskAgent가 선택적으로 reserve를 비축하고 정전 순간 긴급 방전으로 미공급 에너지를 최소화한다. "
        "(CityLearn 2022 phase_all · 별도 런타임)",
    },
}

DEFAULT_SCENARIO = "chesca_mesh"


class MeshChescaUnavailable(RuntimeError):
    """Raised when the optional CHESCA/CityLearn-2.1b12 runtime cannot be initialised."""


@contextmanager
def _official_working_directory() -> Iterator[None]:
    """CHESCA loads pretrained XGBoost models via relative paths → run from official root."""
    for path in (str(CHESCA_SRC), str(CITYLEARN_VENDOR), str(OFFICIAL_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    previous = Path.cwd()
    os.chdir(OFFICIAL_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


def _schema_path(dataset: str) -> Path:
    path = SCHEMA_ROOT / dataset / "schema.json"
    if not path.exists():
        raise MeshChescaUnavailable(f"Unknown CHESCA dataset '{dataset}'.")
    return path


def available_datasets() -> List[str]:
    if not SCHEMA_ROOT.exists():
        return []
    return sorted(p.name for p in SCHEMA_ROOT.iterdir() if (p / "schema.json").exists())


def _build_agent(scenario: str, wrapper: Any) -> Any:
    """Instantiate the controller for a scenario. Must run inside _official_working_directory."""
    kind = SCENARIOS[scenario]["kind"]
    if kind == "external_outage_mpc":
        # 이 시나리오는 CHESCA 워커가 아니라 메인 프로세스의 agent_mesh_runtime이 처리한다.
        # API 레이어가 라우팅하므로 워커까지 오면 잘못된 경로다.
        raise MeshChescaUnavailable(
            f"Scenario '{scenario}' is served by app.services.agent_mesh_runtime, not the CHESCA worker."
        )
    if kind == "official":
        from agents.user_agent import SubmissionAgent

        return SubmissionAgent(wrapper)
    if kind == "mesh":
        from chesca_vs_mesh.mesh_agent import MeshCheca, MeshConfig

        return MeshCheca(wrapper, mesh_config=MeshConfig())
    if kind == "reserve":
        from chesca_vs_mesh.reserve_mesh_agent import ReserveContractMeshCheca

        return ReserveContractMeshCheca(wrapper)
    if kind == "commitment":
        from chesca_vs_mesh.commitment_mesh_agent import CommitmentMeshCheca

        return CommitmentMeshCheca(wrapper)
    if kind == "round_robin":
        from chesca_vs_mesh.round_robin_commitment_agent import RoundRobinCommitmentMeshCheca

        return RoundRobinCommitmentMeshCheca(wrapper)
    raise MeshChescaUnavailable(f"Unknown scenario '{scenario}'.")


class MeshChescaRunner:
    """Incremental CHESCA rollout cache for one (dataset, scenario)."""

    def __init__(self, dataset: str, scenario: str) -> None:
        if scenario not in SCENARIOS:
            raise MeshChescaUnavailable(f"Unknown scenario '{scenario}'.")
        self.dataset = dataset
        self.scenario = scenario

        with _official_working_directory():
            try:
                from citylearn.citylearn import CityLearnEnv
                from chesca_vs_mesh.evaluation import WrapperEnv
                from chesca_vs_mesh.official import official_reward_class
            except Exception as exc:  # pragma: no cover - optional runtime deps
                raise MeshChescaUnavailable(str(exc)) from exc

            schema = str(_schema_path(dataset))
            self._env = CityLearnEnv(schema, reward_function=official_reward_class())
            wrapper = WrapperEnv(self._env)
            self._agent = _build_agent(scenario, wrapper)

            observations = self._reset(self._env)
            self._pending_actions = self._agent.register_reset(observations)

        self._building_names: List[str] = [b.name for b in self._env.buildings]
        self._records: List[Dict[str, Any]] = []
        self._terminated = False
        self._msg_cursor = 0
        self._neg_cursor = 0
        self._time_steps = int(getattr(self._env, "time_steps", 0) or 0)

    # ── rollout ─────────────────────────────────────────────────────

    @property
    def total_steps(self) -> int:
        return self._time_steps

    @property
    def building_count(self) -> int:
        return len(self._building_names)

    def ensure_step(self, step: int) -> None:
        while len(self._records) <= step and not self._terminated:
            self._step_once()

    def get_record(self, step: int) -> Optional[Dict[str, Any]]:
        self.ensure_step(step)
        if 0 <= step < len(self._records):
            return self._records[step]
        return None

    def _step_once(self) -> None:
        step = len(self._records)
        actions = self._pending_actions
        trace = self._drain_logs()

        with _official_working_directory():
            next_observations, done = self._step(self._env, actions)
            record = self._snapshot(step, actions, trace)
            self._records.append(record)
            self._terminated = done
            if not done:
                self._pending_actions = self._agent.predict(next_observations)

    def _drain_logs(self) -> Dict[str, Any]:
        """Collect mesh trace appended by the predict() that produced the pending actions."""
        message_log = list(getattr(self._agent, "message_log", []) or [])
        negotiation_log = list(getattr(self._agent, "negotiation_log", []) or [])
        new_messages = message_log[self._msg_cursor:]
        new_negotiations = negotiation_log[self._neg_cursor:]
        self._msg_cursor = len(message_log)
        self._neg_cursor = len(negotiation_log)
        return {"messages": new_messages, "negotiations": new_negotiations}

    # ── per-step snapshot ───────────────────────────────────────────

    def _snapshot(self, step: int, actions: Any, trace: Dict[str, Any]) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = trace["messages"]
        negotiations: List[Dict[str, Any]] = trace["negotiations"]

        # latest round message per building (sender) → official vs proposed grid + soc.
        latest_by_sender: Dict[int, Dict[str, Any]] = {}
        for msg in messages:
            sender = int(msg.get("sender", -1))
            prev = latest_by_sender.get(sender)
            if prev is None or int(msg.get("round_id", 0)) >= int(prev.get("round_id", 0)):
                latest_by_sender[sender] = msg

        outcome = negotiations[-1] if negotiations else None

        buildings: List[Dict[str, Any]] = []
        for index, building in enumerate(self._env.buildings):
            net = self._series_value(getattr(building, "net_electricity_consumption", []), step)
            solar = abs(self._series_value(getattr(building, "solar_generation", []), step))
            load = self._series_value(getattr(building, "non_shiftable_load", []), step)
            soc_kwh = self._series_value(getattr(building.electrical_storage, "soc", []), step)
            capacity = float(getattr(building.electrical_storage, "capacity", 0.0) or 0.0)
            soc = (soc_kwh / capacity) if capacity > 0 else soc_kwh

            msg = latest_by_sender.get(index)
            official_net = float(msg["official_grid"]) if msg else max(0.0, net)
            mesh_net = float(msg["proposed_grid"]) if msg else max(0.0, net)
            if msg and "soc" in msg:
                soc = float(msg["soc"])

            action_value = self._battery_action_value(actions, index)
            negotiated = bool(msg and not math.isclose(official_net, mesh_net, abs_tol=1e-6))

            buildings.append({
                "building_id": building.name,
                "baseline_net_load_kwh": round(max(0.0, official_net), 3),
                "agent_mesh_net_load_kwh": round(max(0.0, mesh_net), 3),
                "net_load_kwh": round(max(0.0, mesh_net), 3),
                "current_consumption_kwh": round(max(0.0, load), 3),
                "pv_generation_kwh": round(max(0.0, solar), 3),
                "battery_soc": round(min(1.0, max(0.0, soc)), 3),
                "battery_action": self._action_label(action_value),
                "battery_action_value": round(action_value, 4),
                "agent_intervention": negotiated,
                "agent_action_description": (
                    f"peer flex 협상으로 official {official_net:.2f}→{mesh_net:.2f} kWh 조정"
                    if negotiated else None
                ),
            })

        official_district = float(outcome["official_predicted_grid"]) if outcome else sum(
            b["baseline_net_load_kwh"] for b in buildings
        )
        mesh_district = float(outcome["negotiated_predicted_grid"]) if outcome else sum(
            b["agent_mesh_net_load_kwh"] for b in buildings
        )

        return {
            "time_step": step,
            "baseline": round(official_district, 3),
            "agent_mesh": round(mesh_district, 3),
            "baseline_reward": round(-math.pow(max(official_district, 0.0), 1.05), 3),
            "agent_mesh_reward": round(-math.pow(max(mesh_district, 0.0), 1.05), 3),
            "buildings": buildings,
            "negotiation": outcome,
            "messages": messages,
        }

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _reset(env: Any) -> Any:
        result = env.reset()
        if isinstance(result, tuple) and len(result) == 2:
            return result[0]
        return result

    @staticmethod
    def _step(env: Any, actions: Any) -> Tuple[Any, bool]:
        result = env.step(actions)
        if len(result) == 5:
            observations, _, terminated, truncated, _ = result
            return observations, bool(terminated or truncated)
        observations, _, done, _ = result
        return observations, bool(done)

    @staticmethod
    def _series_value(series: Any, step: int) -> float:
        try:
            length = len(series)
        except TypeError:
            return 0.0
        if length == 0:
            return 0.0
        index = min(step, length - 1)
        try:
            return float(series[index])
        except (TypeError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def _battery_action_value(actions: Any, index: int) -> float:
        """CHESCA action layout per building is [cooling, storage, dhw]; storage is index 1."""
        try:
            building_actions = actions[index]
            if len(building_actions) >= 2:
                return float(building_actions[1])
            return float(building_actions[0])
        except (TypeError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def _action_label(action: float) -> str:
        if action > 0.02:
            return "charging"
        if action < -0.02:
            return "discharging"
        return "idle"


# ── module-level cache (one runner per dataset+scenario) ────────────

_runners: Dict[Tuple[str, str], MeshChescaRunner] = {}
_runner_errors: Dict[Tuple[str, str], str] = {}
_lock = threading.RLock()


def _get_runner(dataset: str, scenario: str) -> Optional[MeshChescaRunner]:
    key = (dataset, scenario)
    with _lock:
        if key in _runners:
            return _runners[key]
        if key in _runner_errors:
            return None
        try:
            runner = MeshChescaRunner(dataset, scenario)
            _runners[key] = runner
            return runner
        except Exception as exc:  # pragma: no cover - optional runtime deps
            _runner_errors[key] = str(exc)
            return None


def runtime_status(dataset: str, scenario: str, *, connect: bool = False) -> Dict[str, Any]:
    key = (dataset, scenario)
    runner = _get_runner(dataset, scenario) if connect else _runners.get(key)
    return {
        "chesca_root_detected": CHESCA_ROOT.exists(),
        "dataset": dataset,
        "scenario": scenario,
        "runner_connected": runner is not None,
        "total_steps": runner.total_steps if runner else None,
        "building_count": runner.building_count if runner else None,
        "runtime_error": _runner_errors.get(key),
    }


def get_mesh_chesca_board_snapshot(
    *,
    step: int,
    scenario: str = DEFAULT_SCENARIO,
    dataset: str = DEFAULT_DATASET,
    window: int = 72,
) -> Dict[str, Any]:
    """Assemble a CityLearn-board-compatible snapshot + a mesh_chesca trace block.

    Raises MeshChescaUnavailable if the optional runtime cannot be initialised, so the
    API layer can return a clean error instead of a 500.
    """
    if scenario not in SCENARIOS:
        raise MeshChescaUnavailable(f"Unknown scenario '{scenario}'.")

    runner = _get_runner(dataset, scenario)
    if runner is None:
        raise MeshChescaUnavailable(
            _runner_errors.get((dataset, scenario), "CHESCA runtime unavailable")
        )

    total = runner.total_steps or 1
    step = max(0, min(step, total - 1))
    window = max(1, min(window, 168))
    start = max(0, step - window + 1)

    with _lock:
        points: List[Dict[str, Any]] = []
        for point_step in range(start, step + 1):
            record = runner.get_record(point_step)
            if record is None:
                break
            points.append({
                "time_step": point_step,
                "time_label": f"T+{point_step}",
                "baseline": record["baseline"],
                "agent_mesh": record["agent_mesh"],
                "baseline_reward": record["baseline_reward"],
                "agent_mesh_reward": record["agent_mesh_reward"],
            })

        current = runner.get_record(step) or {"buildings": [], "negotiation": None, "messages": []}
        buildings = [
            {
                **b,
                "history": [
                    {
                        "time_step": p["time_step"],
                        "net_load_kwh": p["agent_mesh"],
                        "baseline_net_load_kwh": p["baseline"],
                        "agent_mesh_net_load_kwh": p["agent_mesh"],
                        "pv_generation_kwh": 0.0,
                        "battery_soc": b.get("battery_soc", 0.0),
                    }
                    for p in points
                ],
            }
            for b in current.get("buildings", [])
        ]

    scenario_meta = SCENARIOS[scenario]
    return {
        "dataset": {
            "id": dataset,
            "path": str((SCHEMA_ROOT / dataset).relative_to(PROJECT_ROOT)),
            "total_steps": total,
            "central_agent": False,
            "active_actions": ["cooling_device", "electrical_storage", "dhw_storage"],
        },
        "runtime": {
            "citylearn_data_connected": True,
            "citylearn_environment_step_connected": True,
            "baseline_runner_connected": True,
            "agent_mesh_action_api_connected": True,
            "source": "mesh_chesca_real_runtime",
            "inference_runner_connected": True,
            **runtime_status(dataset, scenario),
        },
        "step": step,
        "points": points,
        "buildings": buildings,
        "mesh_chesca": {
            "scenario": scenario,
            "scenario_label": scenario_meta["label"],
            "scenario_description": scenario_meta["description"],
            "available_scenarios": [
                {"id": sid, "label": meta["label"], "description": meta["description"]}
                for sid, meta in SCENARIOS.items()
            ],
            "negotiation": current.get("negotiation"),
            "messages": current.get("messages", []),
        },
    }


__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_SCENARIO",
    "MeshChescaUnavailable",
    "SCENARIOS",
    "available_datasets",
    "get_mesh_chesca_board_snapshot",
    "runtime_status",
]

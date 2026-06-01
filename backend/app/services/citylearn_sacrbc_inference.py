"""SACRBC inference bridge for the CityLearn board.

This module keeps the heavy CityLearn/Torch imports lazy so the API can still
serve CSV previews when the optional RL runtime dependencies are not installed.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CITYLEARN_ROOT = PROJECT_ROOT / "CityLearn_old_system"
DATASET_ID = "citylearn_challenge_2022_phase_all"
DATASET_PATH = CITYLEARN_ROOT / "data" / "datasets" / DATASET_ID
SCHEMA_PATH = DATASET_PATH / "schema.json"
INFERENCE_BUNDLE_PATH = CITYLEARN_ROOT / "citylearn" / "best_inference_bundle.pt"


class SACRBCInferenceUnavailable(RuntimeError):
    """Raised when the optional SACRBC runtime cannot be initialized."""


class SACRBCInferenceRunner:
    """Incremental CityLearn SACRBC rollout cache."""

    def __init__(self) -> None:
        if str(CITYLEARN_ROOT) not in sys.path:
            sys.path.insert(0, str(CITYLEARN_ROOT))

        try:
            import torch
            from citylearn.agents.sac import SACRBC
            from citylearn.citylearn import CityLearnEnv
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps.
            raise SACRBCInferenceUnavailable(str(exc)) from exc

        if not INFERENCE_BUNDLE_PATH.exists():
            raise SACRBCInferenceUnavailable(f"Missing inference bundle: {INFERENCE_BUNDLE_PATH}")

        self._torch = torch
        self._env = CityLearnEnv(str(SCHEMA_PATH), central_agent=False, random_seed=0)
        self._observations, _ = self._env.reset()
        self._agent = self._load_agent(SACRBC)
        self._records: List[Dict[str, Any]] = []
        self._terminated = False

    @property
    def model_name(self) -> str:
        return "sacrbc"

    @property
    def model_class(self) -> str:
        return "citylearn.agents.sac.SACRBC"

    def _load_agent(self, agent_cls: Any) -> Any:
        bundle = self._torch.load(INFERENCE_BUNDLE_PATH, map_location="cpu", weights_only=False)
        agent_kwargs = dict(bundle.get("agent_kwargs") or bundle.get("config", {}).get("agent", {}))
        agent = agent_cls(self._env, **agent_kwargs)

        for attr in ("normalized", "norm_mean", "norm_std", "r_norm_mean", "r_norm_std"):
            if attr in bundle:
                setattr(agent, attr, bundle[attr])

        state_groups = {
            "policy_net_state_dicts": "policy_net",
            "soft_q_net1_state_dicts": "soft_q_net1",
            "soft_q_net2_state_dicts": "soft_q_net2",
        }

        for bundle_key, agent_attr in state_groups.items():
            if bundle_key not in bundle:
                continue

            networks = getattr(agent, agent_attr)
            for network, state_dict in zip(networks, bundle[bundle_key]):
                network.load_state_dict(state_dict)
                network.eval()

        return agent

    def ensure_step(self, step: int) -> None:
        while len(self._records) <= step and not self._terminated:
            self._step_once()

    def get_record(self, step: int) -> Optional[Dict[str, Any]]:
        self.ensure_step(step)
        if step < len(self._records):
            return self._records[step]
        return None

    def _step_once(self) -> None:
        step = len(self._records)
        actions = self._agent.predict(self._observations, deterministic=True)
        next_observations, rewards, terminated, truncated, _ = self._env.step(actions)
        self._records.append(self._snapshot(step, actions, rewards))
        self._observations = next_observations
        self._terminated = bool(terminated or truncated)

    def _snapshot(self, step: int, actions: List[List[float]], rewards: List[float]) -> Dict[str, Any]:
        buildings: List[Dict[str, Any]] = []

        for index, building in enumerate(self._env.buildings):
            net = self._series_value(building.net_electricity_consumption, step)
            load = self._series_value(building.non_shiftable_load, step)
            solar = abs(self._series_value(building.solar_generation, step))
            soc = self._series_value(building.electrical_storage.soc, step)
            action = float(actions[index][0]) if index < len(actions) and actions[index] else 0.0

            buildings.append({
                "building_id": building.name,
                "baseline_net_load_kwh": round(max(0.0, net), 2),
                "current_consumption_kwh": round(max(0.0, load), 2),
                "pv_generation_kwh": round(max(0.0, solar), 2),
                "battery_soc": round(min(1.0, max(0.0, soc)), 2),
                "battery_action": self._action_label(action),
                "battery_action_value": round(action, 4),
                "reward": round(float(rewards[index]), 4) if index < len(rewards) else None,
            })

        total_net = sum(item["baseline_net_load_kwh"] for item in buildings)
        reward_values = [item["reward"] for item in buildings if item["reward"] is not None]

        return {
            "time_step": step,
            "baseline": round(total_net, 2),
            "baseline_reward": round(sum(reward_values), 4) if reward_values else round(-(max(total_net, 0.0) ** 1.05), 2),
            "buildings": buildings,
        }

    @staticmethod
    def _series_value(series: Any, step: int) -> float:
        if len(series) == 0:
            return 0.0

        index = min(step, len(series) - 1)
        try:
            return float(series[index])
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _action_label(action: float) -> str:
        if action > 0.02:
            return "charging"
        if action < -0.02:
            return "discharging"
        return "idle"


_runner: Optional[SACRBCInferenceRunner] = None
_runner_error: Optional[str] = None
_lock = threading.RLock()


def get_sacrbc_record(step: int) -> Optional[Dict[str, Any]]:
    runner = _get_runner()
    if runner is None:
        return None

    with _lock:
        return runner.get_record(step)


def get_sacrbc_runtime_status(*, connect: bool = False) -> Dict[str, Any]:
    runner = _get_runner() if connect else _runner
    return {
        "inference_bundle_path": str(INFERENCE_BUNDLE_PATH.relative_to(PROJECT_ROOT)),
        "inference_bundle_detected": INFERENCE_BUNDLE_PATH.exists(),
        "inference_model_name": "sacrbc",
        "inference_model_class": "citylearn.agents.sac.SACRBC",
        "inference_runner_connected": runner is not None,
        "inference_error": _runner_error,
    }


def _get_runner() -> Optional[SACRBCInferenceRunner]:
    global _runner, _runner_error

    if _runner is not None or _runner_error is not None:
        return _runner

    with _lock:
        if _runner is not None or _runner_error is not None:
            return _runner

        try:
            _runner = SACRBCInferenceRunner()
            _runner_error = None
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps.
            _runner = None
            _runner_error = str(exc)

        return _runner

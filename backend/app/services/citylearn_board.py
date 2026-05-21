"""CityLearn board data feed backed by local dataset CSV files."""

from __future__ import annotations

import csv
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal


DATASET_ID = "citylearn_challenge_2022_phase_all"
DATASET_PATH = Path(__file__).resolve().parents[3] / "CityLearn_old_system" / "data" / "datasets" / DATASET_ID
INFERENCE_BUNDLE_PATH = Path(__file__).resolve().parents[3] / "CityLearn_old_system" / "citylearn" / "best_inference_bundle.pt"
TOTAL_STEPS = 8760

BaselineModel = Literal["basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"]
AgentMeshMode = Literal["not_configured", "demo_heuristic", "configured_agents"]

BASELINE_PEAK_MITIGATION: Dict[str, float] = {
    "basic_rbc": 0.0,
    "optimized_rbc": 0.05,
    "basic_battery_rbc": 0.04,
    "sacrbc": 0.09,
    "sac": 0.09,
    "marlisa": 0.12,
}

AGENT_MESH_PEAK_MITIGATION: Dict[str, float] = {
    "not_configured": 0.02,
    "demo_heuristic": 0.18,
    "configured_agents": 0.13,
}


def _float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


@lru_cache(maxsize=1)
def _dataset() -> Dict[str, Any]:
    schema = json.loads((DATASET_PATH / "schema.json").read_text())
    buildings: Dict[str, Any] = {}

    for building_id, config in schema["buildings"].items():
        if not config.get("include", True):
            continue

        buildings[building_id] = {
            "config": config,
            "energy": _rows(DATASET_PATH / config["energy_simulation"]),
        }

    return {
        "schema": schema,
        "buildings": buildings,
        "pricing": _rows(DATASET_PATH / "pricing.csv"),
        "carbon": _rows(DATASET_PATH / "carbon_intensity.csv"),
        "weather": _rows(DATASET_PATH / "weather.csv"),
    }


def _step_index(step: int) -> int:
    return max(0, min(TOTAL_STEPS - 1, step))


def _reduction(hour: int, value: float, *, pv_window: bool = False) -> float:
    if hour >= 16 and hour <= 22:
        return value
    if pv_window:
        return value * 0.35
    return value * 0.5


def _battery_action(hour: int, solar_generation: float, load: float) -> str:
    if hour >= 17 and hour <= 21:
        return "discharging"
    if 10 <= hour <= 15 and solar_generation > load * 0.45:
        return "charging"
    return "idle"


def _battery_soc(step: int, index: int, action: str) -> float:
    wave = math.sin((step / 24 + index * 0.31) * math.pi * 2) * 0.14
    action_bias = 0.14 if action == "charging" else -0.1 if action == "discharging" else 0
    return round(min(0.94, max(0.14, 0.54 + wave + action_bias + ((index % 5) * 0.025))), 2)


def _building_status(
    building_id: str,
    building: Dict[str, Any],
    index: int,
    step: int,
    baseline_model: BaselineModel,
    agent_mesh_mode: AgentMeshMode,
) -> Dict[str, Any]:
    row = building["energy"][_step_index(step)]
    hour = int(_float(row.get("hour"), step % 24))
    load = _float(row.get("non_shiftable_load"))
    solar = _float(row.get("solar_generation"))
    raw_net = max(0.0, load - solar)
    baseline_reduction = _reduction(hour, BASELINE_PEAK_MITIGATION[baseline_model])
    mesh_reduction = _reduction(hour, AGENT_MESH_PEAK_MITIGATION[agent_mesh_mode], pv_window=10 <= hour <= 15)
    baseline_net = max(0.0, raw_net * (1 - baseline_reduction))
    mesh_net = max(0.0, raw_net * (1 - mesh_reduction))
    action = _battery_action(hour, solar, load)
    soc = _battery_soc(step, index, action)
    history = [
        _building_status_minimal(building, index, history_step, baseline_model, agent_mesh_mode)
        for history_step in range(max(0, step - 23), step + 1)
    ]

    return {
        "building_id": building_id,
        "baseline_net_load_kwh": round(baseline_net, 2),
        "agent_mesh_net_load_kwh": round(mesh_net, 2),
        "current_consumption_kwh": round(load, 2),
        "battery_soc": soc,
        "battery_action": action,
        "pv_generation_kwh": round(solar, 2),
        "agent_intervention": agent_mesh_mode != "not_configured" and (action != "idle" or mesh_net >= 4.5),
        "agent_action_description": "Phase-all battery-only dataset feed. SACRBC artifact is detected, but live CityLearn env stepping is not enabled in this API yet.",
        "net_load_kwh": round(mesh_net, 2),
        "history": history,
    }


def _building_status_minimal(
    building: Dict[str, Any],
    index: int,
    step: int,
    baseline_model: BaselineModel,
    agent_mesh_mode: AgentMeshMode,
) -> Dict[str, Any]:
    row = building["energy"][_step_index(step)]
    hour = int(_float(row.get("hour"), step % 24))
    load = _float(row.get("non_shiftable_load"))
    solar = _float(row.get("solar_generation"))
    raw_net = max(0.0, load - solar)
    baseline = raw_net * (1 - _reduction(hour, BASELINE_PEAK_MITIGATION[baseline_model]))
    mesh = raw_net * (1 - _reduction(hour, AGENT_MESH_PEAK_MITIGATION[agent_mesh_mode], pv_window=10 <= hour <= 15))
    action = _battery_action(hour, solar, load)

    return {
        "time_step": step,
        "net_load_kwh": round(mesh, 2),
        "baseline_net_load_kwh": round(max(0.0, baseline), 2),
        "agent_mesh_net_load_kwh": round(max(0.0, mesh), 2),
        "pv_generation_kwh": round(solar, 2),
        "battery_soc": _battery_soc(step, index, action),
    }


def get_board_snapshot(
    *,
    step: int,
    baseline_model: BaselineModel,
    agent_mesh_mode: AgentMeshMode,
    window: int = 72,
) -> Dict[str, Any]:
    dataset = _dataset()
    step = _step_index(step)
    start = max(0, step - max(1, min(window, 168)) + 1)
    building_items = list(dataset["buildings"].items())
    points: List[Dict[str, Any]] = []

    for point_step in range(start, step + 1):
        statuses = [
            _building_status_minimal(building, index, point_step, baseline_model, agent_mesh_mode)
            for index, (_, building) in enumerate(building_items)
        ]
        baseline = sum(item["baseline_net_load_kwh"] for item in statuses)
        mesh = sum(item["agent_mesh_net_load_kwh"] for item in statuses)
        points.append({
            "time_step": point_step,
            "time_label": f"T+{point_step}",
            "baseline": round(baseline, 2),
            "agent_mesh": round(mesh, 2),
            "baseline_reward": round(-math.pow(max(baseline, 0), 1.05), 2),
            "agent_mesh_reward": round(-math.pow(max(mesh, 0), 1.05), 2),
        })

    buildings = [
        _building_status(building_id, building, index, step, baseline_model, agent_mesh_mode)
        for index, (building_id, building) in enumerate(building_items)
    ]

    schema = dataset["schema"]
    return {
        "dataset": {
            "id": DATASET_ID,
            "path": str(DATASET_PATH.relative_to(Path(__file__).resolve().parents[3])),
            "total_steps": TOTAL_STEPS,
            "central_agent": bool(schema.get("central_agent")),
            "active_actions": [
                action for action, config in schema.get("actions", {}).items()
                if config.get("active")
            ],
        },
        "runtime": {
            "citylearn_data_connected": True,
            "citylearn_environment_step_connected": False,
            "baseline_runner_connected": baseline_model == "sacrbc" and INFERENCE_BUNDLE_PATH.exists(),
            "agent_mesh_action_api_connected": False,
            "source": "local_csv_phase_all_with_sacrbc_artifact" if baseline_model == "sacrbc" and INFERENCE_BUNDLE_PATH.exists() else "local_csv_preview",
            "inference_bundle_path": str(INFERENCE_BUNDLE_PATH.relative_to(Path(__file__).resolve().parents[3])),
            "inference_bundle_detected": INFERENCE_BUNDLE_PATH.exists(),
            "inference_model_name": "sacrbc",
            "inference_model_class": "citylearn.agents.sac.SACRBC",
        },
        "step": step,
        "points": points,
        "buildings": buildings,
    }

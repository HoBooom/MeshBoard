"""CityLearn board data feed backed by local dataset CSV files."""

from __future__ import annotations

import csv
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal

from app.services.citylearn_sacrbc_inference import get_sacrbc_record, get_sacrbc_runtime_status


DATASET_ID = "citylearn_challenge_2022_phase_all"
DATASET_PATH = Path(__file__).resolve().parents[3] / "CityLearn_old_system" / "data" / "datasets" / DATASET_ID
TOTAL_STEPS = 8760

BaselineModel = Literal["basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"]
AgentMeshMode = Literal[
    "not_configured",
    "demo_heuristic",
    "configured_agents",
    "grid_agent",
    "macro_mesh",
]

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
    # grid_agent: Grid-Agent plan이 step마다 직렬 적용되는 모드. 초기 peak mitigation
    # 추정치는 demo_heuristic과 configured_agents의 중간값으로 두고, Phase 4 KPI로 보정.
    "grid_agent": 0.16,
    # macro_mesh: 분산 협상(CoProposer × 17 + Negotiator). 분산 의사결정이 더 적극적으로
    # 부담을 분산시킨다는 가설에 따라 grid_agent보다 약간 높게 설정. Phase 4 KPI로 보정.
    "macro_mesh": 0.20,
    # macro_mesh_v2: rollout 검증 + Introspector 복원판. v1 대비 조정 안정성↑ 가설로 약간 높게.
    "macro_mesh_v2": 0.22,
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
    use_sacrbc_inference = baseline_model == "sacrbc"

    for point_step in range(start, step + 1):
        statuses = [
            _building_status_minimal(building, index, point_step, baseline_model, agent_mesh_mode)
            for index, (_, building) in enumerate(building_items)
        ]
        baseline = sum(item["baseline_net_load_kwh"] for item in statuses)
        mesh = sum(item["agent_mesh_net_load_kwh"] for item in statuses)
        inference_record = get_sacrbc_record(point_step) if use_sacrbc_inference else None
        baseline_value = inference_record["baseline"] if inference_record else baseline
        baseline_reward = inference_record["baseline_reward"] if inference_record else round(-math.pow(max(baseline_value, 0), 1.05), 2)

        points.append({
            "time_step": point_step,
            "time_label": f"T+{point_step}",
            "baseline": round(baseline_value, 2),
            "agent_mesh": round(mesh, 2),
            "baseline_reward": round(baseline_reward, 2),
            "agent_mesh_reward": round(-math.pow(max(mesh, 0), 1.05), 2),
        })

    buildings = [
        _building_status(building_id, building, index, step, baseline_model, agent_mesh_mode)
        for index, (building_id, building) in enumerate(building_items)
    ]
    current_inference_record = get_sacrbc_record(step) if use_sacrbc_inference else None

    if current_inference_record:
        inference_by_building = {
            item["building_id"]: item
            for item in current_inference_record["buildings"]
        }

        for building in buildings:
            inference_building = inference_by_building.get(building["building_id"])
            if not inference_building:
                continue

            building["baseline_net_load_kwh"] = inference_building["baseline_net_load_kwh"]
            building["current_consumption_kwh"] = inference_building["current_consumption_kwh"]
            building["pv_generation_kwh"] = inference_building["pv_generation_kwh"]
            building["battery_soc"] = inference_building["battery_soc"]
            building["battery_action"] = inference_building["battery_action"]
            building["baseline_action_value"] = inference_building["battery_action_value"]
            building["agent_action_description"] = "SACRBC checkpoint inference is running against the phase_all CityLearn environment."

            for history_item in building["history"]:
                history_record = get_sacrbc_record(history_item["time_step"])
                if not history_record:
                    continue

                history_building = next(
                    (
                        item for item in history_record["buildings"]
                        if item["building_id"] == building["building_id"]
                    ),
                    None,
                )
                if not history_building:
                    continue

                history_item["baseline_net_load_kwh"] = history_building["baseline_net_load_kwh"]
                history_item["pv_generation_kwh"] = history_building["pv_generation_kwh"]
                history_item["battery_soc"] = history_building["battery_soc"]

    schema = dataset["schema"]
    sacrbc_status = get_sacrbc_runtime_status(connect=use_sacrbc_inference)
    baseline_runner_connected = use_sacrbc_inference and bool(sacrbc_status["inference_runner_connected"])

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
            "citylearn_environment_step_connected": baseline_runner_connected,
            "baseline_runner_connected": baseline_runner_connected,
            "agent_mesh_action_api_connected": False,
            "source": "citylearn_env_sacrbc_checkpoint" if baseline_runner_connected else "local_csv_preview",
            **sacrbc_status,
        },
        "step": step,
        "points": points,
        "buildings": buildings,
    }

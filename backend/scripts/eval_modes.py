"""Unified CityLearn performance evaluation harness.

4개 모드(SARBC baseline / Deterministic Grid-Agent / LLM Planner / MACRO-MESH)를
동일한 실제 CityLearnEnv에서 1~40 step 구동하고, 각 모드의 빌딩별 배터리 action을
env.step()에 주입한 뒤 env.evaluate()로 CityLearn Challenge 공식 KPI를 산출한다.

KPI 매핑 (CityLearn Challenge control track):
  comfort_cost     = discomfort_proportion                         (district)
  emissions_cost   = carbon_emissions_total                        (district)
  grid_cost        = mean(ramping_average, daily_one_minus_load_factor_average,
                          daily_peak_average, all_time_peak_average)
  resilience_cost  = mean(one_minus_thermal_resilience_proportion,
                          power_outage_normalized_unserved_energy_total)
  challenge_cost   = mean(comfort, emissions, grid, resilience)   (non-NaN 항목 평균)

LLM 모드는 RUNYOUR 프록시를 통해 실제 Sonnet 4.6를 호출한다(고강도: planner iter=3, mesh rounds=3).
결과는 step마다 체크포인트 JSON으로 저장되어 장시간 실행 중 크래시에도 부분 결과가 보존된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import numpy as np
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
CITYLEARN_ROOT = PROJECT_ROOT / "CityLearn_old_system"
DATASETS = PROJECT_ROOT / "CityLearn_old_system" / "data" / "datasets"

load_dotenv(BACKEND_ROOT / ".env")
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(CITYLEARN_ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.services.citylearn_grid_agent import run_deterministic_plan  # noqa: E402
from app.services.citylearn_grid_agent_llm import run_llm_planner_loop  # noqa: E402
from app.services.citylearn_macro_mesh import run_macro_mesh_negotiation  # noqa: E402

INFERENCE_BUNDLE = CITYLEARN_ROOT / "citylearn" / "best_inference_bundle.pt"
N_STEPS = 40  # overridable via --steps
WORKSPACE_ID = uuid4()
OUT_DIR = PROJECT_ROOT / "docs"
CKPT_PATH = OUT_DIR / "_eval_checkpoint.json"


# ── KPI extraction ──────────────────────────────────────────────────


def _district_value(df, cost_function: str) -> Optional[float]:
    sub = df[(df["level"] == "district") & (df["cost_function"] == cost_function)]
    if sub.empty:
        return None
    val = float(sub["value"].iloc[0])
    return None if not np.isfinite(val) else val


def _mean_or_none(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(vals)) if vals else None


# ── Grid-Agent board metrics (frontend WorkspacePage.cityLearnMetrics 동일) ──

BOARD_COST_RATE = 0.18    # $/kWh
BOARD_CARBON_RATE = 0.42  # kgCO2/kWh


def board_metrics(loads: List[float]) -> Dict[str, float]:
    """제어된 district net load 시계열 → 보드 5개 지표.

    프론트엔드 WorkspacePage.tsx의 cityLearnMetrics와 동일한 계산:
      총전력소비=Σload, 전력비용=Σload*0.18, 탄소배출=Σload*0.42,
      피크=max(load), 누적Reward=Σ -(max(load,0)^1.05).
    """
    if not loads:
        return {}
    total = float(sum(loads))
    peak = float(max(loads))
    reward = float(sum(-(max(v, 0.0) ** 1.05) for v in loads))
    return {
        "total_consumption_kwh": round(total, 3),
        "power_cost_usd": round(total * BOARD_COST_RATE, 3),
        "carbon_emission_kgco2": round(total * BOARD_CARBON_RATE, 3),
        "peak_load_kw": round(peak, 3),
        "cumulative_reward": round(reward, 3),
    }


def extract_kpis(env) -> Dict[str, Optional[float]]:
    df = env.evaluate()
    comfort = _district_value(df, "discomfort_proportion")
    emissions = _district_value(df, "carbon_emissions_total")
    grid = _mean_or_none([
        _district_value(df, "ramping_average"),
        _district_value(df, "daily_one_minus_load_factor_average"),
        _district_value(df, "daily_peak_average"),
        _district_value(df, "all_time_peak_average"),
    ])
    resilience = _mean_or_none([
        _district_value(df, "one_minus_thermal_resilience_proportion"),
        _district_value(df, "power_outage_normalized_unserved_energy_total"),
    ])
    challenge = _mean_or_none([comfort, emissions, grid, resilience])
    return {
        "comfort_cost": comfort,
        "emissions_cost": emissions,
        "grid_cost": grid,
        "resilience_cost": resilience,
        "challenge_cost": challenge,
        "cost_total": _district_value(df, "cost_total"),
        "electricity_consumption_total": _district_value(df, "electricity_consumption_total"),
    }


# ── live env → board snapshot ───────────────────────────────────────


def _series_last(series, time_step: int) -> float:
    if series is None or len(series) == 0:
        return 0.0
    idx = min(max(time_step, 0), len(series) - 1)
    try:
        return float(series[idx])
    except (TypeError, ValueError):
        return 0.0


def _decision_index(env) -> int:
    """결정 시점(step 시작, env.step 이전)의 '현재 실현 상태' 인덱스.

    CityLearn 시계열은 nec/soc 모두 [time_step] 슬롯이 아직 시뮬레이션되지 않은 placeholder(0)이고,
    실현된 최신 상태는 [time_step-1]에 있다(t=0은 초기 상태 index 0). 이 인덱스를 써야 planner가
    실제 SOC/부하를 본다.
    """
    return max(0, env.time_step - 1)


def build_snapshot(env, step: int, district_history: List[float]) -> Dict[str, Any]:
    """현재 env 상태를 grid-agent 플래너가 읽는 board snapshot 형태로 변환."""
    t = _decision_index(env)
    buildings = []
    for b in env.buildings:
        net = max(0.0, _series_last(b.net_electricity_consumption, t))
        soc = _series_last(b.electrical_storage.soc, t)
        solar = abs(_series_last(b.solar_generation, t))
        buildings.append({
            "building_id": b.name,
            "baseline_net_load_kwh": round(net, 3),
            "agent_mesh_net_load_kwh": round(net, 3),
            "net_load_kwh": round(net, 3),
            "battery_soc": round(min(1.0, max(0.0, soc)), 3),
            "pv_generation_kwh": round(solar, 3),
        })
    points = [{"agent_mesh": round(v, 3), "baseline": round(v, 3)} for v in district_history]
    return {"step": step, "buildings": buildings, "points": points}


def plan_to_actions(env, plan_actions) -> List[List[float]]:
    """CityLearnPlan.actions(빌딩별 배터리 값) → env action 벡터.

    배터리(electrical_storage) 슬롯에만 주입, 나머지 슬롯(dhw/cooling 등)은 0.
    plan에 없는 빌딩은 0(hold).
    """
    action_by_building = {a.building_id: float(a.action) for a in plan_actions}
    actions: List[List[float]] = []
    for i, b in enumerate(env.buildings):
        names = list(env.action_names[i]) if hasattr(env, "action_names") else ["electrical_storage"]
        vec = [0.0] * len(names)
        batt = action_by_building.get(b.name, 0.0)
        if "electrical_storage" in names:
            vec[names.index("electrical_storage")] = max(-1.0, min(1.0, batt))
        actions.append(vec)
    return actions


# ── SARBC agent (trained bundle if compatible, else fresh SACRBC) ────


def load_sarbc_agent(env):
    """Return (agent, kind). kind: 'sacrbc_trained' | 'rbc_fallback'.

    학습된 SACRBC 번들은 2022 phase_all(17빌딩/1액션) 전용이다. 빌딩 수·obs/action shape가
    다른 데이터셋(예: 2023 phase_1, 3빌딩/3액션)에서는 번들 로드가 불가하고, 미학습 SACRBC는
    SAC 경로의 정규화 통계가 없어 predict가 실패한다. 이 경우 SAC-RBC의 RBC 구성요소에 해당하는
    BasicRBC(규칙 기반 제어기)로 대체하고 'rbc_fallback'으로 명확히 표기한다.
    """
    import torch
    from citylearn.agents.sac import SACRBC

    bundle = torch.load(INFERENCE_BUNDLE, map_location="cpu", weights_only=False)
    agent_kwargs = dict(bundle.get("agent_kwargs") or bundle.get("config", {}).get("agent", {}))
    try:
        agent = SACRBC(env, **agent_kwargs)
        for attr in ("normalized", "norm_mean", "norm_std", "r_norm_mean", "r_norm_std"):
            if attr in bundle:
                setattr(agent, attr, bundle[attr])
        for bk, ak in (
            ("policy_net_state_dicts", "policy_net"),
            ("soft_q_net1_state_dicts", "soft_q_net1"),
            ("soft_q_net2_state_dicts", "soft_q_net2"),
        ):
            if bk in bundle:
                for net, sd in zip(getattr(agent, ak), bundle[bk]):
                    net.load_state_dict(sd)
                    net.eval()
        return agent, "sacrbc_trained"
    except Exception as exc:  # noqa: BLE001
        from citylearn.agents.rbc import BasicRBC
        print(f"    [SARBC] trained bundle incompatible ({type(exc).__name__}); using BasicRBC baseline.")
        return BasicRBC(env), "rbc_fallback"


# ── per-mode rollout ────────────────────────────────────────────────


async def rollout(env, mode: str, db, baseline_model: str, agent_mesh_mode: str,
                  planner_iter: int, mesh_rounds: int, n_steps: int,
                  horizons: List[int]) -> Dict[str, Any]:
    obs, _ = env.reset()
    district_history: List[float] = []
    step_times: List[float] = []
    kpis_by_horizon: Dict[str, Any] = {}
    board_by_horizon: Dict[str, Any] = {}
    loads: List[float] = []  # 제어된 district net load (post-step)
    sarbc_agent = None
    sarbc_kind = None
    if mode == "sarbc":
        sarbc_agent, sarbc_kind = load_sarbc_agent(env)

    for step in range(n_steps):
        t0 = time.time()
        di = _decision_index(env)
        district_history.append(sum(
            max(0.0, _series_last(b.net_electricity_consumption, di)) for b in env.buildings
        ))

        if mode == "noctrl":
            actions = [[0.0] * len(env.action_names[i]) for i in range(len(env.buildings))]
        elif mode == "sarbc":
            if sarbc_kind == "sacrbc_trained":
                actions = sarbc_agent.predict(obs, deterministic=True)
            else:
                actions = sarbc_agent.predict(obs)  # RBC baseline
        else:
            snapshot = build_snapshot(env, step, district_history)
            if mode == "deterministic":
                res = run_deterministic_plan(
                    workspace_id=WORKSPACE_ID, snapshot=snapshot, mapping=None,
                    baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
                )
                plan_actions = res.final_plan.actions
            elif mode == "llm_planner":
                res = await run_llm_planner_loop(
                    db=db, workspace_id=WORKSPACE_ID, snapshot=snapshot, mapping=None,
                    baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
                    max_iterations=planner_iter,
                )
                plan_actions = res.final_plan.actions
            elif mode == "macro_mesh":
                res = await run_macro_mesh_negotiation(
                    db=db, workspace_id=WORKSPACE_ID, snapshot=snapshot, mapping=None,
                    baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
                    max_rounds=mesh_rounds, use_llm_proposers=True,
                )
                plan_actions = res.merged_plan.actions
            else:
                raise ValueError(f"unknown mode {mode}")
            actions = plan_to_actions(env, plan_actions)

        obs, _, terminated, truncated, _ = env.step(actions)
        dt = time.time() - t0
        step_times.append(dt)
        # post-step 실현 district net load (배터리 반영). 실현값은 nec[time_step-1]에 저장됨.
        idx = env.time_step - 1
        loads.append(sum(
            max(0.0, float(b.net_electricity_consumption[idx]))
            for b in env.buildings if 0 <= idx < len(b.net_electricity_consumption)
        ))
        print(f"    step {step + 1:2d}/{n_steps}  {dt:6.2f}s", flush=True)

        if (step + 1) in horizons:
            kpis_by_horizon[str(step + 1)] = extract_kpis(env)
            board_by_horizon[str(step + 1)] = board_metrics(loads)
        if terminated or truncated:
            break

    final_h = str(len(step_times))
    if final_h not in kpis_by_horizon:
        kpis_by_horizon[final_h] = extract_kpis(env)
        board_by_horizon[final_h] = board_metrics(loads)

    return {
        "kpis_by_horizon": kpis_by_horizon,
        "kpis": kpis_by_horizon[final_h],  # KPI at the mode's own final horizon
        "board_by_horizon": board_by_horizon,
        "board": board_by_horizon[final_h],
        "final_horizon": len(step_times),
        "sarbc_kind": sarbc_kind,
        "step_time_total_s": round(sum(step_times), 2),
        "step_time_mean_s": round(float(np.mean(step_times)), 3),
        "step_time_max_s": round(float(np.max(step_times)), 3),
        "steps_completed": len(step_times),
    }


# ── orchestration ───────────────────────────────────────────────────


def make_env(schema_path: str):
    from citylearn.citylearn import CityLearnEnv
    return CityLearnEnv(schema_path, central_agent=False, random_seed=0)


def save_ckpt(results: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))


async def main() -> None:
    global N_STEPS, CKPT_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner-iter", type=int, default=3)
    ap.add_argument("--mesh-rounds", type=int, default=3)
    ap.add_argument("--modes", default="sarbc,deterministic,llm_planner,macro_mesh")
    ap.add_argument("--datasets", default="citylearn_challenge_2022_phase_all,citylearn_challenge_2023_phase_1")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--ckpt", default=str(CKPT_PATH))
    # 모드별 step 수 (비용 제어). 사용자 선택: macro_mesh 20, llm_planner 5.
    ap.add_argument("--mode-steps", default="sarbc:40,deterministic:40,macro_mesh:20,llm_planner:5")
    ap.add_argument("--horizons", default="5,20,40")
    args = ap.parse_args()

    N_STEPS = args.steps
    CKPT_PATH = Path(args.ckpt)

    mode_steps = {kv.split(":")[0]: int(kv.split(":")[1]) for kv in args.mode_steps.split(",")}
    all_horizons = [int(h) for h in args.horizons.split(",")]

    modes = args.modes.split(",")
    datasets = args.datasets.split(",")

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)

    results: Dict[str, Any] = {
        "config": {
            "mode_steps": mode_steps, "horizons": all_horizons,
            "planner_iter": args.planner_iter,
            "mesh_rounds": args.mesh_rounds, "llm_model": os.environ.get("DEFAULT_LLM_MODEL"),
            "workspace_id": str(WORKSPACE_ID),
        },
        "datasets": {},
    }
    if CKPT_PATH.exists():
        try:
            results = json.loads(CKPT_PATH.read_text())
        except Exception:  # noqa: BLE001
            pass
    results.setdefault("datasets", {})

    async with Session() as db:
        for ds in datasets:
            schema = str(DATASETS / ds / "schema.json")
            results["datasets"].setdefault(ds, {})
            for mode in modes:
                if mode in results["datasets"][ds]:
                    print(f"[skip] {ds} / {mode} (already in checkpoint)")
                    continue
                n_steps = mode_steps.get(mode, 40)
                horizons = [h for h in all_horizons if h <= n_steps]
                print(f"\n=== {ds} / {mode} (n_steps={n_steps}, horizons={horizons}) ===", flush=True)
                t0 = time.time()
                try:
                    env = make_env(schema)
                    out = await rollout(
                        env, mode, db,
                        baseline_model="sacrbc", agent_mesh_mode="grid_agent",
                        planner_iter=args.planner_iter, mesh_rounds=args.mesh_rounds,
                        n_steps=n_steps, horizons=horizons,
                    )
                    out["wall_time_s"] = round(time.time() - t0, 2)
                    results["datasets"][ds][mode] = out
                    print(f"  -> KPIs: {out['kpis']}  ({out['wall_time_s']}s)", flush=True)
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    results["datasets"][ds][mode] = {"error": f"{type(exc).__name__}: {exc}"}
                save_ckpt(results)

    save_ckpt(results)
    print("\nDONE. Checkpoint at", CKPT_PATH)


if __name__ == "__main__":
    asyncio.run(main())

"""MACRO-MESH v1 vs v2 비교 실험 (3종: 정상 / 돌발상황 / 더미빌딩 추가).

실험 설계
  - 랜덤 시작 step(고정 seed로 재현) + 초기 SOC=0.5 (워밍업 회피). 세 실험 동일 시작 step.
  - E1 normal     : 17빌딩, H step.
  - E2 disturbance: 17빌딩, H step, 중간 5-step 윈도우에 외생 부하 shock(D kWh) 주입(인지+실현부하).
  - E3 building_add: 17+N 더미빌딩(실험용 schema, 기존 CSV 재사용). 협상 확장성/조정품질 측정.
  - 모드: noctrl, sarbc, macro_mesh(v1), macro_mesh_v2.
  - 지표: env KPI(emissions/grid/challenge) + 보드(소비/피크/reward) + 협상품질(conflict/consensus/
    mean_field stddev) + 돌발 resilience(shock중 peak·총초과부하·회복 step). 실험용 schema는 별도
    파일로 쓰고 production schema.json은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import numpy as np
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
CITYLEARN = PROJECT / "CityLearn_old_system"
DS_DIR = CITYLEARN / "data" / "datasets" / "citylearn_challenge_2022_phase_all"

load_dotenv(BACKEND / ".env")
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(CITYLEARN))

import importlib.util  # noqa: E402

_eh = importlib.util.spec_from_file_location("eh", str(BACKEND / "scripts" / "eval_modes.py"))
eh = importlib.util.module_from_spec(_eh); _eh.loader.exec_module(eh)
_v2 = importlib.util.spec_from_file_location("mmv2", str(BACKEND / "scripts" / "macro_mesh_v2.py"))
mmv2 = importlib.util.module_from_spec(_v2); _v2.loader.exec_module(mmv2)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models.agent import Agent  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.citylearn_macro_mesh import run_macro_mesh_negotiation  # noqa: E402

OUT = PROJECT / "docs"
CKPT = OUT / "_exp_v2_checkpoint.json"
WS = uuid4()


def build_exp_schema(name: str, start: int, horizon: int, initial_soc: float, n_dummy: int) -> str:
    s = json.load(open(DS_DIR / "schema.json"))
    s["simulation_start_time_step"] = start
    s["simulation_end_time_step"] = start + horizon
    for b in s["buildings"].values():
        b["electrical_storage"]["attributes"]["initial_soc"] = initial_soc
    srcs = list(s["buildings"].keys())
    for i in range(n_dummy):
        s["buildings"][f"Building_{18 + i}"] = copy.deepcopy(s["buildings"][srcs[i % len(srcs)]])
    path = DS_DIR / f"schema_{name}.json"
    json.dump(s, open(path, "w"))
    return str(path)


def make_env(schema_path: str):
    from citylearn.citylearn import CityLearnEnv
    return CityLearnEnv(schema_path, central_agent=False, random_seed=0)


def board_from_loads(loads: List[float]) -> Dict[str, float]:
    return eh.board_metrics(loads)


async def run_rollout(env, mode: str, db, agents, n_steps: int,
                      shock_window: Optional[tuple], shock_kwh: float) -> Dict[str, Any]:
    obs, _ = env.reset()
    district_hist: List[float] = []
    loads: List[float] = []
    step_times: List[float] = []
    mesh_diag: List[Dict[str, Any]] = []
    strategy_notes: List[str] = []

    sarbc_agent = sarbc_kind = None
    if mode == "sarbc":
        sarbc_agent, sarbc_kind = eh.load_sarbc_agent(env)
    v2ctl = None
    if mode == "macro_v2":
        v2ctl = mmv2.MacroMeshV2Controller(
            building_agent=agents["building"], coordinator_agent=agents["coordinator"],
            model=None, max_rounds=2, workspace_id=WS,
        )

    nb = len(env.buildings)
    llm_used = llm_fallback = 0
    for step in range(n_steps):
        t0 = time.time()
        di = eh._decision_index(env)
        base_district = sum(max(0.0, eh._series_last(b.net_electricity_consumption, di)) for b in env.buildings)
        prev_district = district_hist[-1] if district_hist else base_district
        district_hist.append(base_district)
        in_shock = shock_window is not None and shock_window[0] <= step < shock_window[1]

        snap = eh.build_snapshot(env, step, district_hist)
        if in_shock:  # 외생 부하 shock을 빌딩별로 분배해 agent가 인지
            add = shock_kwh / max(nb, 1)
            for b in snap["buildings"]:
                b["net_load_kwh"] = round(b["net_load_kwh"] + add, 3)
                b["agent_mesh_net_load_kwh"] = round(b.get("agent_mesh_net_load_kwh", b["net_load_kwh"]) + add, 3)

        diag: Dict[str, Any] = {}
        if mode == "noctrl":
            actions = [[0.0] * len(env.action_names[i]) for i in range(nb)]
        elif mode == "sarbc":
            actions = sarbc_agent.predict(obs, deterministic=True) if sarbc_kind == "sacrbc_trained" else sarbc_agent.predict(obs)
        elif mode == "macro_v1":
            res = await run_macro_mesh_negotiation(
                db=db, workspace_id=WS, snapshot=snap, mapping=None,
                baseline_model="sacrbc", agent_mesh_mode="macro_mesh",
                max_rounds=2, use_llm_proposers=True,
            )
            actions = eh.plan_to_actions(env, res.merged_plan.actions)
            stats = getattr(res, "proposer_stats", None) or {}
            llm_used += stats.get("llm", 0)
            llm_fallback += stats.get("fallback", 0)
            last = res.rounds[-1] if res.rounds else None
            mf = last.mean_field if last else None
            stddev = mf.stddev_action if mf else 0.0
            mean_abs = mf.mean_abs_action if mf else 0.0
            diag = {"conflict_count": len(last.conflicts) if last else 0,
                    "consensus": round(1.0 - min(1.0, stddev / (mean_abs + 1e-6)) if mean_abs > 0 else 1.0, 3),
                    "mean_field_stddev": round(stddev, 3), "n_actions": len(res.merged_plan.actions)}
        elif mode == "macro_v2":
            acts, diag = await v2ctl.decide(snap, prev_district)
            actions = eh.plan_to_actions(env, acts)
            # v2 는 자체 컨트롤러를 쓰므로 proposer 통계를 여기서 따로 읽는다.
            # 이걸 빼먹으면 v2 결과만 llm_ratio 없이 남아 v1 과 나란히 비교할 수 없다.
            v2_stats = getattr(v2ctl.proposer, "stats", None) or {}
            llm_used = v2_stats.get("llm", 0)
            llm_fallback = v2_stats.get("fallback", 0)
        else:
            raise ValueError(mode)

        obs, _, term, trunc, _ = env.step(actions)
        realized = sum(max(0.0, float(b.net_electricity_consumption[env.time_step - 1])) for b in env.buildings)
        board_load = realized + (shock_kwh if in_shock else 0.0)
        loads.append(board_load)
        reward = -(max(board_load, 0.0) ** 1.05)
        if mode == "macro_v2":
            await v2ctl.observe(db, reward)
            strategy_notes.append(v2ctl.strategy["note"][:200])
        if diag:
            diag["in_shock"] = in_shock
            mesh_diag.append(diag)
        step_times.append(time.time() - t0)
        print(f"    [{mode}] step {step+1}/{n_steps} {step_times[-1]:5.1f}s load={board_load:.1f}{' SHOCK' if in_shock else ''}", flush=True)
        if term or trunc:
            break

    kpis = eh.extract_kpis(env)
    board = board_from_loads(loads)
    out: Dict[str, Any] = {
        "kpis": kpis, "board": board, "sarbc_kind": sarbc_kind,
        "step_time_mean_s": round(float(np.mean(step_times)), 2),
        "loads": [round(x, 2) for x in loads],
        "steps": len(loads),
    }
    if mesh_diag:
        out["mesh_quality"] = {
            "avg_conflict": round(float(np.mean([d["conflict_count"] for d in mesh_diag])), 3),
            "avg_consensus": round(float(np.mean([d["consensus"] for d in mesh_diag])), 3),
            "avg_mean_field_stddev": round(float(np.mean([d["mean_field_stddev"] for d in mesh_diag])), 3),
            "avg_n_actions": round(float(np.mean([d["n_actions"] for d in mesh_diag])), 2),
        }
    if shock_window is not None:
        sw = loads[shock_window[0]:shock_window[1]]
        pre = loads[:shock_window[0]]
        base_peak = max(pre) if pre else 0.0
        recovery = None
        for k, L in enumerate(loads[shock_window[1]:]):
            if L <= base_peak * 1.1:
                recovery = k + 1
                break
        out["resilience"] = {
            "shock_peak_kw": round(max(sw), 2) if sw else None,
            "shock_total_excess_kwh": round(sum(max(0.0, L - base_peak) for L in sw), 2) if sw else None,
            "pre_shock_peak_kw": round(base_peak, 2),
            "recovery_steps": recovery,
        }
    if strategy_notes:
        out["final_strategy_note"] = strategy_notes[-1]
    if llm_used or llm_fallback:
        total = llm_used + llm_fallback
        out["llm_proposals"] = {
            "llm": llm_used,
            "heuristic_fallback": llm_fallback,
            "llm_ratio": round(llm_used / total, 3) if total else 0.0,
        }
    return out


def save(results, path: Path = None):
    OUT.mkdir(exist_ok=True)
    (path or CKPT).write_text(json.dumps(results, indent=2, ensure_ascii=False))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=3000)
    ap.add_argument("--horizon", type=int, default=15)
    ap.add_argument("--soc", type=float, default=0.5)
    ap.add_argument("--dummies", type=int, default=2)
    ap.add_argument("--shock-mult", type=float, default=2.0)
    ap.add_argument("--modes", default="noctrl,sarbc,macro_v1,macro_v2")
    ap.add_argument("--exps", default="normal,disturbance,building_add")
    ap.add_argument("--ckpt", default=str(CKPT),
                    help="결과 파일 경로. 기본값은 문서가 인용하는 체크포인트다.")
    ap.add_argument("--force", action="store_true",
                    help="기존 결과와 실험 조건이 다를 때도 같은 파일에 이어 쓴다.")
    args = ap.parse_args()

    ckpt_path = Path(args.ckpt)
    H = args.horizon
    eng = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as db:
        agents = {
            "building": (await db.execute(select(Agent).where(Agent.name == "Building Battery Agent"))).scalars().first(),
            "coordinator": (await db.execute(select(Agent).where(Agent.name == "City Grid Coordinator"))).scalars().first(),
        }

        results: Dict[str, Any] = {}
        if ckpt_path.exists():
            try:
                results = json.loads(ckpt_path.read_text())
            except Exception:  # noqa: BLE001
                results = {}

        # 실험 조건은 재현에 필요한 정보이므로 매번 새로 기록한다. 예전에는 setdefault 라서
        # horizon 을 바꿔 재실행하면 결과만 덮이고 config 는 옛 값으로 남아, 파일이 조용히
        # 어긋난 상태가 됐다.
        config = {
            "start": args.start,
            "horizon": H,
            "initial_soc": args.soc,
            "dummies": args.dummies,
            "shock_mult": args.shock_mult,
            "workspace_id": str(WS),
            # 어떤 모델로 낸 수치인지 남기지 않으면 나중에 표를 해석할 수 없다.
            "llm_model": settings.llm_default_model,
            "llm_base_url": settings.llm_base_url,
            "llm_external_gateway": settings.llm_uses_external_gateway,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        comparable = ("start", "horizon", "initial_soc", "dummies", "shock_mult", "llm_model")
        previous = results.get("config")
        if previous:
            drift = {k: (previous.get(k), config[k]) for k in comparable if previous.get(k) != config[k]}
            if drift and not args.force:
                print(f"ERROR: {ckpt_path} 의 기존 결과와 실험 조건이 다릅니다.", file=sys.stderr)
                for key, (was, now) in drift.items():
                    print(f"  {key}: {was!r} → {now!r}", file=sys.stderr)
                print("  다른 파일에 쓰려면 --ckpt, 이어 쓰려면 --force 를 사용하세요.", file=sys.stderr)
                return 1
        results["config"] = {**(previous or {}), **config}
        results.setdefault("experiments", {})

        # 외생 shock 크기 = 정상 district load 추정 × shock_mult (start 시점 기준)
        probe = make_env(build_exp_schema("probe", args.start, 3, args.soc, 0))
        probe.reset()
        normal_load = sum(max(0.0, float(b.net_electricity_consumption[0])) for b in probe.buildings)
        shock_kwh = round(normal_load * args.shock_mult, 2)
        results["config"]["normal_load_est"] = round(normal_load, 2)
        results["config"]["shock_kwh"] = shock_kwh
        try:
            os.remove(DS_DIR / "schema_probe.json")
        except OSError:
            pass

        exp_specs = {
            "normal":       dict(n_dummy=0, shock_window=None),
            "disturbance":  dict(n_dummy=0, shock_window=(5, 10)),
            "building_add": dict(n_dummy=args.dummies, shock_window=None),
        }
        for exp in args.exps.split(","):
            spec = exp_specs[exp]
            schema = build_exp_schema(exp, args.start, H, args.soc, spec["n_dummy"])
            results["experiments"].setdefault(exp, {})
            for mode in args.modes.split(","):
                if mode in results["experiments"][exp]:
                    print(f"[skip] {exp}/{mode}")
                    continue
                print(f"\n=== {exp} / {mode} (start={args.start}, H={H}, dummies={spec['n_dummy']}, shock={spec['shock_window']}) ===", flush=True)
                t0 = time.time()
                try:
                    env = make_env(schema)
                    out = await run_rollout(env, mode, db, agents, H,
                                            spec["shock_window"], shock_kwh if spec["shock_window"] else 0.0)
                    out["wall_s"] = round(time.time() - t0, 1)
                    results["experiments"][exp][mode] = out
                    print(f"  -> board={out['board']} kpi_chal={out['kpis'].get('challenge_cost')}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    import traceback; traceback.print_exc()
                    results["experiments"][exp][mode] = {"error": f"{type(exc).__name__}: {exc}"}
                save(results, ckpt_path)
        save(results, ckpt_path)
    print("\nDONE", ckpt_path)


if __name__ == "__main__":
    asyncio.run(main())

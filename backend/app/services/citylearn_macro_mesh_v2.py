"""MACRO-MESH v2 — 논문(MACRO-LLM) 3모듈 복원판 (프로덕션 서비스).

v1(`citylearn_macro_mesh.py`) 대비 추가:
  1) CoProposer **rollout 검증**: 협상 merged plan을 k-step surrogate(즉시부하+peak+ramp+SOC건강도)로
     평가해 후보집합 중 최선을 채택(`rollout_revise`).
  2) **Introspector (LLM semantic-gradient)**: reward 추세를 보고 자연어 전략 + aggressiveness/
     discharge_bias를 갱신(`introspect`). 보드는 단일 step 요청이므로 workspace별 전략을
     `_V2_STRATEGY_CACHE`에 누적해 step 간 temporal reasoning을 유지한다.
  3) StrategyProposer: v1 building proposer에 전략 note를 주입.

board 연동: `run_macro_mesh_v2_negotiation`는 v1과 동일한 `MacroMeshRunResult`를 반환해
`/citylearn/macro-mesh/negotiate` 엔드포인트·프론트 렌더링을 그대로 재사용한다.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.citylearn_grid_agent import (
    AgentMeshMode,
    BaselineModel,
    CityLearnAction,
    CityLearnPlan,
    PlanIteration,
)
from app.services.agent_runtime import invoke_agent
from app.services.citylearn_grid_agent import (
    ConstraintValidator,
    OperatorSummarizer,
    SandboxExecutor,
    TopologyAnalyzer,
    ViolationDetector,
)
from app.services.citylearn_grid_agent_constants import (
    BATTERY_POWER_KWH,
    HEURISTIC_CONFIDENCE,
    PEAK_PENALTY_WEIGHT,
    PEAK_THRESHOLD_KWH,
    RAMP_PENALTY_WEIGHT,
    RAMP_THRESHOLD_KWH,
    SOC_DELTA_PER_UNIT_ACTION,
)
from app.services.citylearn_macro_mesh import (
    CoProposerClient,
    MacroMeshRunResult,
    Negotiator,
    load_building_agent,
    merge_proposals,
)
from app.services.citylearn_grid_agent_llm import load_coordinator_agent

logger = logging.getLogger(__name__)

SOC_TARGET_LOW = 0.30
SOC_TARGET_HIGH = 0.90
SOC_LOW_W = 8.0
SOC_HIGH_W = 8.0

# 보드는 step별 stateless 요청 → workspace별 전략을 누적해 Introspector temporal reasoning 유지.
# 단일 프로세스 in-memory 캐시(프로덕션 다중 워커면 외부 store로 교체).
_V2_STRATEGY_CACHE: Dict[str, Dict[str, Any]] = {}


def _default_strategy() -> Dict[str, Any]:
    return {"note": "", "aggressiveness": 1.0, "discharge_bias": 0.0, "reward_hist": []}


def reset_v2_strategy(workspace_id: UUID) -> None:
    _V2_STRATEGY_CACHE.pop(str(workspace_id), None)


# ── StrategyProposer ────────────────────────────────────────────────


class StrategyProposer(CoProposerClient):
    """v1 building proposer + operator_strategy_note 주입."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.strategy_note: str = ""

    async def _invoke_llm(self, asset, round_index, mean_field, conflicts,
                          forbidden_action_keys, district_load):
        if self.agent is None:
            return None
        from app.services.citylearn_macro_mesh import (
            _parse_building_proposal_json, BuildingProposal,
        )
        prompt = json.dumps({
            "task": "single_building_battery_proposal",
            "round_index": round_index,
            "your_building_id": asset.building_id,
            "battery_soc": round(asset.battery_soc, 3),
            "net_load_kwh": round(asset.net_load_kwh, 3),
            "pv_generation_kwh": round(asset.pv_generation_kwh, 3),
            "district_net_load_kwh": round(district_load, 3),
            "operator_strategy_note": self.strategy_note or "(none yet)",
            "mean_field": mean_field.model_dump(mode="json") if mean_field else None,
            "conflicts": [c.model_dump(mode="json") for c in conflicts] if conflicts else [],
            "forbidden_action_keys": list(forbidden_action_keys),
            "instructions": (
                "operator_strategy_note(coordinator의 누적 전략)를 반영해 당신 building의 단일 "
                "action ∈ [-1.0,1.0]만 제안하십시오. SOC<0.2 방전 금지, SOC>0.9 충전 금지. "
                "final answer는 {\"action\":<float>,\"mode\":\"charge|discharge|hold\",\"confidence\":<0..1>,"
                "\"rationale\":\"...\",\"expected_local_effect\":\"...\"} JSON을 answer로 담으십시오."
            ),
        }, ensure_ascii=False)
        result = await invoke_agent(agent=self.agent, user_message=prompt, model=self.model)
        parsed = _parse_building_proposal_json(str(result.get("output") or ""))
        if parsed is None:
            return None
        av = max(-1.0, min(1.0, float(parsed.get("action", 0.0))))
        mode = parsed.get("mode")
        if mode not in {"charge", "discharge", "hold"}:
            mode = "charge" if av > 0.05 else "discharge" if av < -0.05 else "hold"
        try:
            conf = max(0.0, min(1.0, float(parsed.get("confidence", HEURISTIC_CONFIDENCE))))
        except (TypeError, ValueError):
            conf = HEURISTIC_CONFIDENCE
        return BuildingProposal(
            building_id=asset.building_id, round_index=round_index,
            proposed_action=av, confidence=conf,
            rationale=str(parsed.get("rationale") or "LLM proposal"),
            expected_local_effect=str(parsed.get("expected_local_effect") or ""),
            kind="llm",
        )


# ── CoProposer rollout surrogate ────────────────────────────────────


def _soc_penalty(soc: float) -> float:
    if soc < SOC_TARGET_LOW:
        return (SOC_TARGET_LOW - soc) * SOC_LOW_W
    if soc > SOC_TARGET_HIGH:
        return (soc - SOC_TARGET_HIGH) * SOC_HIGH_W
    return 0.0


def _district_load(net_map: Dict[str, float], act_map: Dict[str, float]) -> float:
    return sum(max(0.0, net + act_map.get(b, 0.0) * BATTERY_POWER_KWH) for b, net in net_map.items())


def _imm_cost(load: float, prev: float) -> float:
    return (load + max(0.0, load - PEAK_THRESHOLD_KWH) * PEAK_PENALTY_WEIGHT
            + max(0.0, abs(load - prev) - RAMP_THRESHOLD_KWH) * RAMP_PENALTY_WEIGHT)


def _plan_value(net_map, soc_map, act_map, prev_district) -> float:
    cost = _imm_cost(_district_load(net_map, act_map), prev_district)
    for b, soc in soc_map.items():
        post = max(0.0, min(1.0, soc + act_map.get(b, 0.0) * SOC_DELTA_PER_UNIT_ACTION))
        cost += _soc_penalty(post)
    return cost


def rollout_revise(merged: CityLearnPlan, snapshot: Dict[str, Any], prev_district: float,
                   aggressiveness: float, discharge_bias: float) -> Tuple[CityLearnPlan, Dict[str, Any]]:
    """k-step surrogate rollout으로 후보집합 중 최선을 채택."""
    net_map: Dict[str, float] = {}
    soc_map: Dict[str, float] = {}
    for b in snapshot.get("buildings", []):
        bid = str(b.get("building_id"))
        net_map[bid] = float(b.get("net_load_kwh", b.get("agent_mesh_net_load_kwh", 0.0)))
        soc_map[bid] = float(b.get("battery_soc", 0.5))

    base = {a.building_id: float(a.action) for a in merged.actions}
    biased = {b: max(-1.0, min(1.0, v + (discharge_bias if v <= 0 else 0.0))) for b, v in base.items()}
    candidates: Dict[str, Dict[str, float]] = {
        "full": biased,
        "discharge_only": {b: v for b, v in biased.items() if v < 0},
        "charge_low_soc": {b: v for b, v in biased.items() if v > 0 and soc_map.get(b, 1) < SOC_TARGET_LOW + 0.1},
        "hold": {},
    }
    scored = {k: _plan_value(net_map, soc_map, v, prev_district) for k, v in candidates.items()}
    best_key = min(scored, key=scored.get)

    actions: List[CityLearnAction] = []
    for bid, val in candidates[best_key].items():
        val = max(-1.0, min(1.0, val * aggressiveness))
        if abs(val) < 0.05:
            continue
        actions.append(CityLearnAction(
            building_id=bid, action=round(val, 3),
            mode="charge" if val > 0 else "discharge",
            reason=f"v2 rollout:{best_key}", expected_effect="", confidence=0.7,
        ))
    diag = {"rollout_choice": best_key, "rollout_scores": {k: round(v, 2) for k, v in scored.items()},
            "projected_district_load": round(_district_load(net_map, candidates[best_key]), 3)}
    return CityLearnPlan(strategy_summary=f"v2 rollout={best_key}", actions=actions, risk_assessment=""), diag


# ── Introspector (LLM semantic gradient) ────────────────────────────


async def introspect(coordinator_agent, reward_hist: List[float], strategy: Dict[str, Any],
                     last_diag: Dict[str, Any], model: Optional[str]) -> Dict[str, Any]:
    if coordinator_agent is None or len(reward_hist) < 2:
        return strategy
    recent = reward_hist[-4:]
    prompt = json.dumps({
        "task": "introspect_and_update_strategy",
        "recent_rewards": [round(r, 2) for r in recent],
        "reward_trend": round(recent[-1] - recent[0], 3),
        "current_strategy_note": strategy.get("note", ""),
        "current_aggressiveness": strategy.get("aggressiveness", 1.0),
        "current_discharge_bias": strategy.get("discharge_bias", 0.0),
        "last_step_diag": last_diag,
        "instructions": (
            "당신은 district coordinator입니다. 최근 reward(0에 가까울수록 좋음)와 추세를 보고 다음 step "
            "battery 협상 전략을 1~2문장 자연어(semantic gradient)로 갱신하고, aggressiveness(0.5~1.5)와 "
            "discharge_bias(-0.2~0.2)를 조정하십시오. reward가 나빠지면 크게, 안정적이면 미세 조정. "
            "final answer는 {\"note\":\"...\",\"aggressiveness\":<float>,\"discharge_bias\":<float>} JSON."
        ),
    }, ensure_ascii=False)
    try:
        result = await invoke_agent(agent=coordinator_agent, user_message=prompt, model=model)
        raw = str(result.get("output") or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        # coordinator가 tool 호출 등으로 prose를 섞을 수 있으므로 "aggressiveness"를 포함한
        # JSON object 후보를 우선 선택, 없으면 greedy match로 fallback.
        data: Dict[str, Any] = {}
        for cand in re.findall(r"\{[^{}]*\}", raw, re.DOTALL):
            if "aggressiveness" in cand or "note" in cand:
                try:
                    data = json.loads(cand)
                    break
                except json.JSONDecodeError:
                    continue
        if not data:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    data = {}
        return {
            "note": str(data.get("note", strategy.get("note", "")))[:400],
            "aggressiveness": max(0.5, min(1.5, float(data.get("aggressiveness", strategy.get("aggressiveness", 1.0))))),
            "discharge_bias": max(-0.2, min(0.2, float(data.get("discharge_bias", strategy.get("discharge_bias", 0.0))))),
            "reward_hist": reward_hist,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("v2 introspect failed: %s", exc)
        return strategy


def _prev_district(snapshot: Dict[str, Any], fallback: float) -> float:
    points = snapshot.get("points") or []
    if len(points) >= 2:
        p = points[-2]
        return float(p.get("agent_mesh", p.get("baseline", fallback)))
    return fallback


# ── Board single-step entrypoint ────────────────────────────────────


async def run_macro_mesh_v2_negotiation(
    *,
    db: Optional[AsyncSession],
    workspace_id: UUID,
    snapshot: Dict[str, Any],
    mapping: Optional[Dict[str, Any]],
    baseline_model: Optional[BaselineModel],
    agent_mesh_mode: Optional[AgentMeshMode],
    max_rounds: int = 2,
    use_llm_proposers: bool = True,
    model: Optional[str] = None,
) -> MacroMeshRunResult:
    """v2 단일 step 협상 → rollout 검증 → Introspector 전략 갱신(workspace 캐시). v1과 동일 반환형."""
    analyzer = TopologyAnalyzer()
    detector = ViolationDetector()
    executor = SandboxExecutor()
    validator = ConstraintValidator()
    summarizer = OperatorSummarizer()

    topology = analyzer.analyze(
        workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    initial_violations = detector.detect_initial(topology=topology, snapshot=snapshot)

    building_agent = await load_building_agent(db) if use_llm_proposers else None
    coordinator = await load_coordinator_agent(db)
    strategy = _V2_STRATEGY_CACHE.get(str(workspace_id)) or _default_strategy()

    proposer = StrategyProposer(agent=building_agent, use_llm=use_llm_proposers and building_agent is not None, model=model)
    proposer.strategy_note = strategy["note"]
    negotiator = Negotiator(proposer=proposer)
    rounds = await negotiator.run(
        assets=topology.controllable_assets, district_load=topology.district_net_load_kwh,
        max_rounds=max_rounds, initial_forbidden_keys=(),
    )
    merged = merge_proposals(rounds)

    prev_d = _prev_district(snapshot, topology.district_net_load_kwh)
    revised, rdiag = rollout_revise(merged, snapshot, prev_d, strategy["aggressiveness"], strategy["discharge_bias"])

    sandbox = executor.execute(snapshot=snapshot, plan=revised)
    topo_after = analyzer.analyze(
        workspace_id=workspace_id, snapshot=sandbox, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    validation = validator.validate(
        snapshot_before=snapshot, snapshot_after=sandbox,
        topology_before=topology, topology_after=topo_after,
        plan=revised, initial_violations=initial_violations, forbidden_action_keys=(),
    )

    # Introspector: 이번 plan의 projected load를 reward proxy로 사용해 다음 step 전략 갱신.
    reward = -(max(rdiag["projected_district_load"], 0.0) ** 1.05)
    strategy["reward_hist"] = (strategy.get("reward_hist") or []) + [reward]
    last_diag = {"conflict_count": len(rounds[-1].conflicts) if rounds else 0,
                 "rollout_choice": rdiag["rollout_choice"], "n_actions": len(revised.actions)}
    new_strategy = await introspect(coordinator, strategy["reward_hist"], strategy, last_diag, model)
    new_strategy["reward_hist"] = strategy["reward_hist"][-8:]
    _V2_STRATEGY_CACHE[str(workspace_id)] = new_strategy

    plan_trace = [PlanIteration(
        iteration=1,
        planner_kind="llm" if (use_llm_proposers and building_agent) else "heuristic",
        planner_output={
            "version": "v2",
            "rollout_choice": rdiag["rollout_choice"],
            "rollout_scores": rdiag["rollout_scores"],
            "strategy_note": new_strategy["note"][:200],
            "aggressiveness": round(new_strategy["aggressiveness"], 2),
            "discharge_bias": round(new_strategy["discharge_bias"], 3),
            "rounds_count": len(rounds),
        },
        plan=revised, validation=validation,
        route_decision=f"v2 rollout={rdiag['rollout_choice']}" + (" approved" if validation.approved else " rejected"),
    )]
    operator_summary = (
        f"[MACRO-Mesh v2] rollout={rdiag['rollout_choice']} · actions {len(revised.actions)} · "
        f"aggr {new_strategy['aggressiveness']:.2f} · " + summarizer.summarize(
            topology=topology, plan=revised, validation=validation, initial_violations=initial_violations)
    )

    return MacroMeshRunResult(
        topology=topology,
        initial_violations=initial_violations,
        rounds=rounds,
        merged_plan=revised,
        plan_iteration_trace=plan_trace,
        validation=validation,
        operator_summary=operator_summary,
        requested_at=datetime.now(timezone.utc),
        forbidden_action_keys=list(validation.forbidden_action_keys),
    )


__all__ = [
    "StrategyProposer",
    "rollout_revise",
    "introspect",
    "run_macro_mesh_v2_negotiation",
    "reset_v2_strategy",
]

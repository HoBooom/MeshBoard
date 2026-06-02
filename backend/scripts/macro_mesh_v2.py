"""실험용 v2 컨트롤러 — 프로덕션 서비스(app.services.citylearn_macro_mesh_v2)를 재사용.

핵심 로직(StrategyProposer / rollout_revise / introspect)은 프로덕션 서비스에 단일 소스로 두고,
여기서는 실험 하니스(exp_v2.py)가 env loop를 직접 구동할 때 쓰는 stateful 컨트롤러만 정의한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.schemas.citylearn_grid_agent import CityLearnAction
from app.services.citylearn_grid_agent import TopologyAnalyzer
from app.services.citylearn_macro_mesh import Negotiator, merge_proposals
from app.services.citylearn_macro_mesh_v2 import (  # noqa: F401  (re-export)
    StrategyProposer,
    introspect,
    rollout_revise,
)


class MacroMeshV2Controller:
    """step 간 전략을 누적하는 v2 컨트롤러(실험 하니스용). 보드 연동은 서비스의
    run_macro_mesh_v2_negotiation을 사용한다."""

    def __init__(self, building_agent, coordinator_agent, model: Optional[str] = None,
                 max_rounds: int = 2, workspace_id=None) -> None:
        self.proposer = StrategyProposer(agent=building_agent, use_llm=building_agent is not None, model=model)
        self.coordinator = coordinator_agent
        self.model = model
        self.max_rounds = max_rounds
        self.workspace_id = workspace_id
        self.strategy: Dict[str, Any] = {"note": "", "aggressiveness": 1.0, "discharge_bias": 0.0}
        self.reward_hist: List[float] = []
        self.last_diag: Dict[str, Any] = {}

    async def decide(self, snapshot: Dict[str, Any], prev_district: float) -> Tuple[List[CityLearnAction], Dict[str, Any]]:
        topo = TopologyAnalyzer().analyze(
            workspace_id=self.workspace_id, snapshot=snapshot, mapping=None,
            baseline_model="sacrbc", agent_mesh_mode="macro_mesh",
        )
        self.proposer.strategy_note = self.strategy["note"]
        rounds = await Negotiator(proposer=self.proposer).run(
            assets=topo.controllable_assets, district_load=topo.district_net_load_kwh,
            max_rounds=self.max_rounds, initial_forbidden_keys=(),
        )
        merged = merge_proposals(rounds)
        revised, rdiag = rollout_revise(
            merged, snapshot, prev_district, self.strategy["aggressiveness"], self.strategy["discharge_bias"],
        )
        last = rounds[-1] if rounds else None
        mf = last.mean_field if last else None
        stddev = mf.stddev_action if mf else 0.0
        mean_abs = mf.mean_abs_action if mf else 0.0
        consensus = 1.0 - min(1.0, stddev / (mean_abs + 1e-6)) if mean_abs > 0 else 1.0
        diag = {
            "conflict_count": len(last.conflicts) if last else 0,
            "mean_field_stddev": round(stddev, 3),
            "consensus": round(consensus, 3),
            "rounds": len(rounds),
            "rollout_choice": rdiag["rollout_choice"],
            "n_actions": len(revised.actions),
            "strategy_note": self.strategy["note"][:120],
            "aggressiveness": round(self.strategy["aggressiveness"], 2),
            "discharge_bias": round(self.strategy["discharge_bias"], 3),
        }
        self.last_diag = {k: diag[k] for k in ("conflict_count", "consensus", "rollout_choice", "n_actions")}
        return revised.actions, diag

    async def observe(self, db, reward: float) -> None:
        self.reward_hist.append(reward)
        self.strategy = await introspect(
            self.coordinator, self.reward_hist, self.strategy, self.last_diag, self.model,
        )

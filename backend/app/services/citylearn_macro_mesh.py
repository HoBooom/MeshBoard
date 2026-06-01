"""MACRO-Mesh 분산 협상 엔진 (AM-macro-002, Phase 3).

설계: docs/architecture/02_paper_macro_llm.md + 03_recommended_architecture.md.

구성 요소
- CoProposerClient: 단일 Building Battery Agent invoke 래퍼 (LLM 또는 heuristic)
- MeanFieldAggregator: round 종료 후 평균/분산/critical_soc_ratio 산출
- ConflictDetector: 규칙 기반 conflict 탐지 (over_discharge / soc_risk / fairness / resource_contention)
- Negotiator: round 1 → 2 orchestration. **17 building agent invoke는 asyncio.gather로 병렬**.

병렬화: 한 round의 모든 building agent invoke는 `await asyncio.gather(*tasks)`로 동시 실행.
직렬이면 17 × 60s = 17분/step, 병렬이면 LLM proxy의 동시성 한도 내에서 max(latency) ~ 60s/step.

안전 원칙
- 모든 LLM output은 schema(action ∈ [-1, 1], building_id 일치) 검증
- LLM 호출 실패 / parsing 실패 시 heuristic proposer fallback (per-building)
- max_rounds=2, per-building timeout 30s
- 최종 merged_plan은 Grid-Agent 파이프라인의 SandboxExecutor + ConstraintValidator로 재검증
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.schemas.citylearn_grid_agent import (
    AgentMeshMode,
    BaselineModel,
    CityLearnAction,
    CityLearnPlan,
    CityLearnValidationResult,
    CityLearnViolation,
    ControllableAsset,
    PlanIteration,
    TopologySummary,
)
from app.schemas.citylearn_macro_mesh import (
    BuildingProposal,
    ConflictReport,
    MAX_ROUNDS_DEFAULT,
    MacroMeshNegotiateResponse,
    MeanFieldSummary,
    NEGOTIATE_TIMEOUT_SECONDS,
    NegotiationFeedback,
    NegotiationRound,
    ROUND_INDEX_MAX,
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
    HEURISTIC_CHARGE_ACTION,
    HEURISTIC_CONFIDENCE,
    HEURISTIC_DISCHARGE_ACTION,
    SOC_HARD_LOWER,
    SOC_HARD_UPPER,
    SOC_SOFT_LOWER,
    SOC_SOFT_UPPER,
)


logger = logging.getLogger(__name__)

BUILDING_AGENT_NAME = "Building Battery Agent"

# Building proposal LLM call의 timeout. 17개 병렬이라 한 building이 느리면 전체가 지연되므로
# Grid-Agent Coordinator(180s)보다 짧게.
BUILDING_INVOKE_TIMEOUT_SECONDS = 45.0

# Conflict thresholds — 규칙 기반.
OVER_DISCHARGE_RATIO = 0.6      # round의 60% 이상이 discharge면 conflict
FAIRNESS_ABS_STDDEV = 0.40       # |action| 표준편차 임계값
CRITICAL_SOC_RATIO_THRESHOLD = 0.30  # critical SOC 빌딩 비율 30% 초과 시 conflict


# ── Result container ────────────────────────────────────────────────


@dataclass
class MacroMeshRunResult:
    topology: TopologySummary
    initial_violations: List[CityLearnViolation]
    rounds: List[NegotiationRound]
    merged_plan: CityLearnPlan
    plan_iteration_trace: List[PlanIteration]
    validation: CityLearnValidationResult
    operator_summary: str
    requested_at: datetime
    forbidden_action_keys: List[str] = field(default_factory=list)


# ── CoProposerClient ────────────────────────────────────────────────


class CoProposerClient:
    """단일 Building Battery Agent를 invoke해 BuildingProposal을 생성한다."""

    def __init__(self, agent: Optional[Agent], use_llm: bool, model: Optional[str] = None) -> None:
        self.agent = agent
        self.use_llm = use_llm and agent is not None
        self.model = model

    async def propose(
        self,
        *,
        asset: ControllableAsset,
        round_index: int,
        mean_field: Optional[MeanFieldSummary],
        conflicts: Sequence[ConflictReport],
        forbidden_action_keys: Sequence[str],
        district_load: float,
    ) -> BuildingProposal:
        if self.use_llm:
            try:
                proposal = await asyncio.wait_for(
                    self._invoke_llm(asset, round_index, mean_field, conflicts, forbidden_action_keys, district_load),
                    timeout=BUILDING_INVOKE_TIMEOUT_SECONDS,
                )
                if proposal is not None:
                    return proposal
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                logger.warning("CoProposer LLM failed for %s: %s", asset.building_id, exc)

        return _heuristic_propose(asset, round_index, mean_field, conflicts, forbidden_action_keys, district_load)

    async def _invoke_llm(
        self,
        asset: ControllableAsset,
        round_index: int,
        mean_field: Optional[MeanFieldSummary],
        conflicts: Sequence[ConflictReport],
        forbidden_action_keys: Sequence[str],
        district_load: float,
    ) -> Optional[BuildingProposal]:
        if self.agent is None:
            return None
        prompt = json.dumps(
            {
                "task": "single_building_battery_proposal",
                "round_index": round_index,
                "your_building_id": asset.building_id,
                "battery_soc": round(asset.battery_soc, 3),
                "net_load_kwh": round(asset.net_load_kwh, 3),
                "pv_generation_kwh": round(asset.pv_generation_kwh, 3),
                "district_net_load_kwh": round(district_load, 3),
                "mean_field": mean_field.model_dump(mode="json") if mean_field else None,
                "conflicts": [c.model_dump(mode="json") for c in conflicts] if conflicts else [],
                "forbidden_action_keys": list(forbidden_action_keys),
                "instructions": (
                    "당신 자신의 building에 대한 단일 action ∈ [-1.0, 1.0]만 제안하십시오. "
                    "다른 building을 제어하면 안 됩니다. SOC<0.2면 discharge 금지, SOC>0.9면 charge 금지. "
                    "final answer는 {\"action\": <float>, \"mode\": \"charge|discharge|hold\", \"confidence\": <float 0..1>, "
                    "\"rationale\": \"...\", \"expected_local_effect\": \"...\"} JSON을 stringify해서 answer field에 담으십시오."
                ),
            },
            ensure_ascii=False,
        )
        result = await invoke_agent(agent=self.agent, user_message=prompt, model=self.model)
        raw = str(result.get("output") or "")
        parsed = _parse_building_proposal_json(raw)
        if parsed is None:
            return None
        action_value = float(parsed.get("action", 0.0))
        action_value = max(-1.0, min(1.0, action_value))
        mode = parsed.get("mode")
        if mode not in {"charge", "discharge", "hold"}:
            mode = "charge" if action_value > 0.05 else "discharge" if action_value < -0.05 else "hold"
        try:
            confidence = float(parsed.get("confidence", HEURISTIC_CONFIDENCE))
        except (TypeError, ValueError):
            confidence = HEURISTIC_CONFIDENCE
        confidence = max(0.0, min(1.0, confidence))
        return BuildingProposal(
            building_id=asset.building_id,
            round_index=round_index,
            proposed_action=action_value,
            confidence=confidence,
            rationale=str(parsed.get("rationale") or "LLM proposal"),
            expected_local_effect=str(parsed.get("expected_local_effect") or ""),
            kind="llm",
            raw_output_preview=raw[:200],
        )


def _parse_building_proposal_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        candidate = json.loads(match.group(0))
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        return None
    return None


def _heuristic_propose(
    asset: ControllableAsset,
    round_index: int,
    mean_field: Optional[MeanFieldSummary],
    conflicts: Sequence[ConflictReport],
    forbidden_action_keys: Sequence[str],
    district_load: float,
) -> BuildingProposal:
    """LLM 없는 결정적 proposer. round 2에서는 mean_field/conflicts를 반영해 보수적."""
    soc = asset.battery_soc
    net = asset.net_load_kwh
    forbidden = set(forbidden_action_keys)

    over_discharge = any(c.type == "over_discharge" for c in conflicts) if conflicts else False
    fairness_concern = any(c.type == "fairness" and asset.building_id in c.building_ids for c in conflicts)

    def _action_key(b: str, a: float) -> str:
        return f"{b}:{round(a, 2):.2f}"

    if soc < SOC_SOFT_LOWER:
        action_value = HEURISTIC_CHARGE_ACTION if net < 2.0 else 0.0
        mode = "charge" if action_value > 0 else "hold"
        rationale = f"SOC {soc:.2f} < soft_lower {SOC_SOFT_LOWER}, 충전 보호"
    elif soc > SOC_SOFT_UPPER and net > 3.0:
        action_value = HEURISTIC_DISCHARGE_ACTION
        if over_discharge:
            action_value *= 0.5  # round 2 조정
            rationale = f"district 과방전 우려 → discharge 강도 축소 ({action_value:+.2f})"
        elif fairness_concern:
            action_value *= 0.5
            rationale = f"fairness 경고 → discharge 강도 축소"
        else:
            rationale = f"SOC {soc:.2f}, 고부하 → discharge"
        mode = "discharge"
    elif net > 5.0 and soc > SOC_HARD_LOWER + 0.1:
        action_value = HEURISTIC_DISCHARGE_ACTION * 0.7
        if over_discharge:
            action_value = 0.0
        mode = "discharge" if action_value < 0 else "hold"
        rationale = f"district peak 기여 빌딩 → discharge" if action_value < 0 else "over_discharge로 hold"
    else:
        action_value = 0.0
        mode = "hold"
        rationale = "현재 상태 균형, hold"

    # forbidden 회피
    key = _action_key(asset.building_id, action_value)
    if key in forbidden:
        action_value = 0.0
        mode = "hold"
        rationale += " (forbidden key 회피)"

    confidence = HEURISTIC_CONFIDENCE if asset.has_mapping else HEURISTIC_CONFIDENCE * 0.6
    expected = f"{action_value * BATTERY_POWER_KWH:+.2f} kWh net load"
    return BuildingProposal(
        building_id=asset.building_id,
        round_index=round_index,
        proposed_action=action_value,
        confidence=confidence,
        rationale=rationale,
        expected_local_effect=expected,
        kind="heuristic",
    )


# ── MeanFieldAggregator ─────────────────────────────────────────────


class MeanFieldAggregator:
    def aggregate(
        self,
        *,
        proposals: Sequence[BuildingProposal],
        assets: Sequence[ControllableAsset],
        round_index: int,
    ) -> MeanFieldSummary:
        actions = [p.proposed_action for p in proposals]
        n = len(actions)
        mean = sum(actions) / n if n else 0.0
        var = sum((a - mean) ** 2 for a in actions) / n if n else 0.0
        std = math.sqrt(var)
        abs_actions = [abs(a) for a in actions]
        mean_abs = sum(abs_actions) / n if n else 0.0
        discharge = sum(1 for p in proposals if p.proposed_action < -0.05)
        charge = sum(1 for p in proposals if p.proposed_action > 0.05)
        hold = n - discharge - charge
        critical = sum(1 for a in assets if a.battery_soc < SOC_HARD_LOWER + 0.05 or a.battery_soc > SOC_HARD_UPPER - 0.05)
        critical_ratio = (critical / len(assets)) if assets else 0.0
        expected_delta = sum(p.proposed_action * BATTERY_POWER_KWH for p in proposals)
        return MeanFieldSummary(
            round_index=round_index,
            proposal_count=n,
            mean_action=round(mean, 3),
            stddev_action=round(std, 3),
            mean_abs_action=round(mean_abs, 3),
            discharge_count=discharge,
            charge_count=charge,
            hold_count=hold,
            critical_soc_ratio=round(critical_ratio, 3),
            expected_district_load_delta_kwh=round(expected_delta, 3),
        )


# ── ConflictDetector ────────────────────────────────────────────────


class ConflictDetector:
    def detect(
        self,
        *,
        proposals: Sequence[BuildingProposal],
        assets: Sequence[ControllableAsset],
        mean_field: MeanFieldSummary,
    ) -> List[ConflictReport]:
        conflicts: List[ConflictReport] = []
        n = len(proposals)
        if n == 0:
            return conflicts

        # 1) over_discharge — 60% 이상 빌딩이 discharge
        discharging = [p.building_id for p in proposals if p.proposed_action < -0.05]
        if len(discharging) / n >= OVER_DISCHARGE_RATIO:
            conflicts.append(ConflictReport(
                type="over_discharge",
                severity=min(1.0, len(discharging) / n),
                building_ids=discharging,
                description=f"{len(discharging)}/{n} 빌딩이 동시에 discharge — district SOC 위기",
            ))

        # 2) soc_risk — 각 building의 proposed action 적용 시 hard bound 위반 위험
        asset_by_id = {a.building_id: a for a in assets}
        soc_risk_buildings: List[str] = []
        for p in proposals:
            asset = asset_by_id.get(p.building_id)
            if asset is None:
                continue
            from app.services.citylearn_grid_agent_constants import SOC_DELTA_PER_UNIT_ACTION
            predicted_soc = asset.battery_soc + p.proposed_action * SOC_DELTA_PER_UNIT_ACTION
            if predicted_soc < SOC_HARD_LOWER or predicted_soc > SOC_HARD_UPPER:
                soc_risk_buildings.append(p.building_id)
        if soc_risk_buildings:
            conflicts.append(ConflictReport(
                type="soc_risk",
                severity=min(1.0, len(soc_risk_buildings) / n),
                building_ids=soc_risk_buildings,
                description=f"적용 시 SOC hard bound 위반 위험: {len(soc_risk_buildings)} 빌딩",
            ))

        # 3) fairness — |action| 표준편차가 임계값 초과 시 극단치 빌딩 식별
        if mean_field.stddev_action > FAIRNESS_ABS_STDDEV and mean_field.mean_abs_action > 0:
            extreme = [
                p.building_id for p in proposals
                if abs(abs(p.proposed_action) - mean_field.mean_abs_action) > FAIRNESS_ABS_STDDEV
            ]
            if extreme:
                conflicts.append(ConflictReport(
                    type="fairness",
                    severity=min(1.0, mean_field.stddev_action / FAIRNESS_ABS_STDDEV),
                    building_ids=extreme,
                    description=f"|action| 표준편차 {mean_field.stddev_action:.2f}, 부담 집중 빌딩 {len(extreme)}개",
                ))

        # 4) resource_contention — critical SOC 빌딩이 다수인데 discharge 시도
        if mean_field.critical_soc_ratio > CRITICAL_SOC_RATIO_THRESHOLD:
            critical_discharge = [
                p.building_id for p in proposals
                if p.proposed_action < -0.05
                and (a := asset_by_id.get(p.building_id))
                and (a.battery_soc < SOC_HARD_LOWER + 0.05 or a.battery_soc > SOC_HARD_UPPER - 0.05)
            ]
            if critical_discharge:
                conflicts.append(ConflictReport(
                    type="resource_contention",
                    severity=mean_field.critical_soc_ratio,
                    building_ids=critical_discharge,
                    description=f"critical SOC 빌딩 비율 {mean_field.critical_soc_ratio:.2f}, 동시 discharge 경합",
                ))

        return conflicts


# ── Negotiator ──────────────────────────────────────────────────────


class Negotiator:
    """round 1 → 2 orchestration. 17 building agent invoke는 asyncio.gather로 병렬."""

    def __init__(self, proposer: CoProposerClient) -> None:
        self.proposer = proposer
        self.aggregator = MeanFieldAggregator()
        self.detector = ConflictDetector()

    async def run(
        self,
        *,
        assets: Sequence[ControllableAsset],
        district_load: float,
        max_rounds: int,
        initial_forbidden_keys: Sequence[str],
    ) -> List[NegotiationRound]:
        rounds: List[NegotiationRound] = []
        mean_field: Optional[MeanFieldSummary] = None
        conflicts: List[ConflictReport] = []
        forbidden_keys: List[str] = list(initial_forbidden_keys)

        for round_index in range(min(max_rounds, ROUND_INDEX_MAX + 1)):
            t0 = time.time()

            # 병렬 invoke (사용자 요청: asyncio.gather)
            tasks = [
                self.proposer.propose(
                    asset=a,
                    round_index=round_index,
                    mean_field=mean_field,
                    conflicts=conflicts,
                    forbidden_action_keys=forbidden_keys,
                    district_load=district_load,
                )
                for a in assets
            ]
            proposals = await asyncio.gather(*tasks, return_exceptions=False)
            elapsed = time.time() - t0

            new_mean_field = self.aggregator.aggregate(
                proposals=proposals, assets=assets, round_index=round_index,
            )
            new_conflicts = self.detector.detect(
                proposals=proposals, assets=assets, mean_field=new_mean_field,
            )

            # 다음 round를 위한 feedback 생성 (마지막 round 직전까지)
            feedback_map: Dict[str, NegotiationFeedback] = {}
            if round_index < min(max_rounds, ROUND_INDEX_MAX + 1) - 1:
                for p in proposals:
                    feedback_map[p.building_id] = NegotiationFeedback(
                        target_building_id=p.building_id,
                        mean_field=new_mean_field,
                        conflicts=[c for c in new_conflicts if not c.building_ids or p.building_id in c.building_ids],
                        forbidden_action_keys=forbidden_keys,
                        instruction="mean_field + conflict를 반영해 round 2 proposal을 다시 발의하십시오.",
                    )

            rounds.append(NegotiationRound(
                round_index=round_index,
                proposals=list(proposals),
                mean_field=new_mean_field,
                conflicts=new_conflicts,
                feedback_by_building=feedback_map,
                elapsed_seconds=round(elapsed, 2),
            ))

            mean_field = new_mean_field
            conflicts = new_conflicts

        return rounds


# ── Merge & Run ─────────────────────────────────────────────────────


def merge_proposals(rounds: Sequence[NegotiationRound]) -> CityLearnPlan:
    """마지막 round의 proposal을 최종 plan으로 채택."""
    if not rounds:
        return CityLearnPlan(strategy_summary="(no rounds)", actions=[], risk_assessment="empty")
    last = rounds[-1]
    actions: List[CityLearnAction] = []
    for p in last.proposals:
        if abs(p.proposed_action) < 0.05:
            continue
        mode = "charge" if p.proposed_action > 0 else "discharge"
        actions.append(CityLearnAction(
            building_id=p.building_id,
            action=p.proposed_action,
            mode=mode,
            reason=p.rationale[:140],
            expected_effect=p.expected_local_effect[:140],
            confidence=p.confidence,
        ))
    strategy = (
        f"round {last.round_index + 1}/{len(rounds)} 협상 후 채택 — "
        f"discharge {last.mean_field.discharge_count} / charge {last.mean_field.charge_count} / hold {last.mean_field.hold_count}, "
        f"|action| std={last.mean_field.stddev_action:.2f}"
    )
    risk = ", ".join([f"{c.type}({c.severity:.2f})" for c in last.conflicts]) or "no conflict"
    return CityLearnPlan(strategy_summary=strategy, actions=actions, risk_assessment=risk)


async def load_building_agent(db: Optional[AsyncSession]) -> Optional[Agent]:
    if db is None:
        return None
    try:
        result = await db.execute(select(Agent).where(Agent.name == BUILDING_AGENT_NAME))
        return result.scalars().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("AM-macro-002: building agent lookup failed: %s", exc)
        return None


async def run_macro_mesh_negotiation(
    *,
    db: Optional[AsyncSession],
    workspace_id: UUID,
    snapshot: Mapping[str, Any],
    mapping: Optional[Mapping[str, Any]],
    baseline_model: Optional[BaselineModel],
    agent_mesh_mode: Optional[AgentMeshMode],
    max_rounds: int = MAX_ROUNDS_DEFAULT,
    use_llm_proposers: bool = False,
    initial_forbidden_keys: Sequence[str] = (),
    model: Optional[str] = None,
) -> MacroMeshRunResult:
    """분산 협상 → 최종 plan → Grid-Agent SandboxExecutor + ConstraintValidator로 검증."""
    analyzer = TopologyAnalyzer()
    detector = ViolationDetector()
    executor = SandboxExecutor()
    validator = ConstraintValidator()
    summarizer = OperatorSummarizer()

    topology_before = analyzer.analyze(
        workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    initial_violations = detector.detect_initial(topology=topology_before, snapshot=snapshot)

    building_agent = await load_building_agent(db) if use_llm_proposers else None
    proposer = CoProposerClient(agent=building_agent, use_llm=use_llm_proposers, model=model)
    negotiator = Negotiator(proposer=proposer)

    rounds = await negotiator.run(
        assets=topology_before.controllable_assets,
        district_load=topology_before.district_net_load_kwh,
        max_rounds=max_rounds,
        initial_forbidden_keys=initial_forbidden_keys,
    )

    merged_plan = merge_proposals(rounds)
    sandbox = executor.execute(snapshot=snapshot, plan=merged_plan)
    topology_after = analyzer.analyze(
        workspace_id=workspace_id, snapshot=sandbox, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    validation = validator.validate(
        snapshot_before=snapshot, snapshot_after=sandbox,
        topology_before=topology_before, topology_after=topology_after,
        plan=merged_plan, initial_violations=initial_violations,
        forbidden_action_keys=initial_forbidden_keys,
    )
    plan_iteration_trace = [
        PlanIteration(
            iteration=1,
            planner_kind="llm" if use_llm_proposers and building_agent else "heuristic",
            planner_output={
                "rounds_count": len(rounds),
                "final_round_mean_field": rounds[-1].mean_field.model_dump(mode="json") if rounds else None,
            },
            plan=merged_plan,
            validation=validation,
            route_decision="approved" if validation.approved else "rejected (post-negotiation)",
        )
    ]
    operator_summary = summarizer.summarize(
        topology=topology_before, plan=merged_plan,
        validation=validation, initial_violations=initial_violations,
    )

    return MacroMeshRunResult(
        topology=topology_before,
        initial_violations=initial_violations,
        rounds=rounds,
        merged_plan=merged_plan,
        plan_iteration_trace=plan_iteration_trace,
        validation=validation,
        operator_summary=operator_summary,
        requested_at=datetime.now(timezone.utc),
        forbidden_action_keys=list(validation.forbidden_action_keys),
    )


__all__ = [
    "BUILDING_AGENT_NAME",
    "CoProposerClient",
    "ConflictDetector",
    "MacroMeshRunResult",
    "MeanFieldAggregator",
    "Negotiator",
    "load_building_agent",
    "merge_proposals",
    "run_macro_mesh_negotiation",
]

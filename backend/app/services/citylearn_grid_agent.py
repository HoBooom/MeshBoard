"""Grid-Agent deterministic 엔진 (Phase 1, LLM 없음).

논문 매핑: TopologyAgent / PlannerAgent / ExecutorAgent / ValidatorAgent / SummarizerAgent.
원본 설계: docs/architecture/01_paper_grid_agent.md, docs/architecture/03_recommended_architecture.md.
Feature 추적: docs/architecture/feature_list.json (AM-engine-001).

핵심 원칙
- 모든 module은 deterministic pure Python. LLM 호출 없음.
- SandboxExecutor는 deepcopy로 동작, 입력 snapshot을 절대 변경하지 않는다.
- score_after >= score_before 이거나 새로운 SOC/invalid_action violation 발생 시 rejected.
- magic number는 citylearn_grid_agent_constants에서만 정의한다.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from app.schemas.citylearn_grid_agent import (
    ACTION_MAX,
    ACTION_MIN,
    ActionMode,
    AgentMeshMode,
    BaselineModel,
    CityLearnAction,
    CityLearnPlan,
    CityLearnValidationResult,
    CityLearnViolation,
    ControllableAsset,
    PlanIteration,
    TopologySummary,
    UNIT_MAX,
    UNIT_MIN,
)
from app.services.citylearn_grid_agent_constants import (
    BATTERY_POWER_KWH,
    BUILDING_HIGH_LOAD_KWH,
    BUILDING_LOW_LOAD_KWH,
    FAIRNESS_PENALTY_WEIGHT,
    FAIRNESS_STD_THRESHOLD,
    HEURISTIC_CHARGE_ACTION,
    HEURISTIC_CONFIDENCE,
    HEURISTIC_DISCHARGE_ACTION,
    PEAK_PENALTY_WEIGHT,
    PEAK_THRESHOLD_KWH,
    RAMP_PENALTY_WEIGHT,
    RAMP_THRESHOLD_KWH,
    SOC_DELTA_PER_UNIT_ACTION,
    SOC_HARD_LOWER,
    SOC_HARD_UPPER,
    SOC_PENALTY_PER_BUILDING,
    SOC_SOFT_LOWER,
    SOC_SOFT_UPPER,
)


# ── Helpers ─────────────────────────────────────────────────────────


def _safe_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _action_key(building_id: str, action: float) -> str:
    """forbidden_action_keys 누적용 결정적 키."""
    return f"{building_id}:{round(action, 2):.2f}"


def _classify_mode(action: float) -> ActionMode:
    if action > 0.05:
        return "charge"
    if action < -0.05:
        return "discharge"
    return "hold"


def _clip_action(action: float) -> float:
    return max(ACTION_MIN, min(ACTION_MAX, float(action)))


def _stddev(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


# ── TopologyAnalyzer ────────────────────────────────────────────────


class TopologyAnalyzer:
    """Board snapshot + workspace.metadata_.agent_building_mapping → TopologySummary."""

    def analyze(
        self,
        *,
        workspace_id: UUID,
        snapshot: Mapping[str, Any],
        mapping: Optional[Mapping[str, Any]],
        baseline_model: Optional[BaselineModel] = None,
        agent_mesh_mode: Optional[AgentMeshMode] = None,
    ) -> TopologySummary:
        buildings: List[Dict[str, Any]] = list(snapshot.get("buildings", []))
        step = int(snapshot.get("step", 0))
        baseline_model = baseline_model or snapshot.get("baseline_model") or _infer_baseline(snapshot)
        agent_mesh_mode = agent_mesh_mode or snapshot.get("agent_mesh_mode") or _infer_mesh_mode(snapshot)

        assignment_by_id = _parse_mapping(mapping)

        assets: List[ControllableAsset] = []
        district_load = 0.0
        mapped_count = 0

        for building in buildings:
            building_id = str(building.get("building_id"))
            assignment = assignment_by_id.get(building_id)
            has_mapping = bool(assignment and assignment.get("assigned_agent_id"))
            if has_mapping:
                mapped_count += 1

            net_load = float(building.get("agent_mesh_net_load_kwh", building.get("net_load_kwh", 0.0)))
            district_load += net_load

            assets.append(
                ControllableAsset(
                    building_id=building_id,
                    assigned_agent_id=_safe_uuid(assignment.get("assigned_agent_id") if assignment else None),
                    assigned_agent_name=(assignment or {}).get("assigned_agent_name"),
                    battery_soc=_clamp_unit(building.get("battery_soc", 0.5)),
                    net_load_kwh=round(net_load, 3),
                    pv_generation_kwh=round(float(building.get("pv_generation_kwh", 0.0)), 3),
                    has_mapping=has_mapping,
                )
            )

        return TopologySummary(
            workspace_id=workspace_id,
            step=step,
            baseline_model=baseline_model,
            agent_mesh_mode=agent_mesh_mode,
            building_count=len(buildings),
            mapped_building_count=mapped_count,
            district_net_load_kwh=round(district_load, 3),
            controllable_assets=assets,
        )


def _parse_mapping(mapping: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """workspace metadata의 agent_building_mapping 블록을 {building_id: assignment} 로 평탄화."""
    if not mapping:
        return {}
    raw = mapping.get("agent_building_mapping") if "agent_building_mapping" in mapping else mapping
    if not isinstance(raw, Mapping):
        return {}

    buildings_field = raw.get("buildings")
    if not isinstance(buildings_field, Iterable):
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for entry in buildings_field:
        if not isinstance(entry, Mapping):
            continue
        building_id = entry.get("building_id")
        if not isinstance(building_id, str):
            continue
        result[building_id] = {
            "assigned_agent_id": entry.get("assigned_agent_id"),
            "assigned_agent_name": entry.get("assigned_agent_name"),
            "metadata": entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else None,
        }
    return result


def _infer_baseline(snapshot: Mapping[str, Any]) -> BaselineModel:
    runtime = snapshot.get("runtime") or {}
    if runtime.get("inference_runner_connected"):
        return "sacrbc"
    return "basic_rbc"


def _infer_mesh_mode(snapshot: Mapping[str, Any]) -> AgentMeshMode:
    runtime = snapshot.get("runtime") or {}
    if runtime.get("agent_mesh_action_api_connected"):
        return "configured_agents"
    return "demo_heuristic"


def _clamp_unit(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(UNIT_MIN, min(UNIT_MAX, f))


# ── ViolationDetector ───────────────────────────────────────────────


@dataclass(frozen=True)
class _DistrictStats:
    current_load: float
    previous_load: Optional[float]


class ViolationDetector:
    """peak / ramping / soc / mapping / fairness / invalid_action 탐지."""

    def detect_initial(
        self,
        *,
        topology: TopologySummary,
        snapshot: Mapping[str, Any],
    ) -> List[CityLearnViolation]:
        stats = _district_stats(snapshot)
        violations: List[CityLearnViolation] = []
        violations.extend(self._peak(stats))
        violations.extend(self._ramping(stats))
        violations.extend(self._soc(topology))
        violations.extend(self._mapping(topology))
        return violations

    def detect_post_action(
        self,
        *,
        sandbox_snapshot: Mapping[str, Any],
        sandbox_topology: TopologySummary,
        plan: CityLearnPlan,
        valid_building_ids: Iterable[str],
    ) -> List[CityLearnViolation]:
        stats = _district_stats(sandbox_snapshot)
        violations: List[CityLearnViolation] = []
        violations.extend(self._peak(stats))
        violations.extend(self._ramping(stats))
        violations.extend(self._soc(sandbox_topology))
        violations.extend(self._invalid_actions(plan, set(valid_building_ids)))
        violations.extend(self._fairness(plan))
        return violations

    # ── private rules ──────────────────────────────────────────────

    @staticmethod
    def _peak(stats: _DistrictStats) -> List[CityLearnViolation]:
        if stats.current_load <= PEAK_THRESHOLD_KWH:
            return []
        excess = stats.current_load - PEAK_THRESHOLD_KWH
        severity = min(1.0, excess / max(PEAK_THRESHOLD_KWH, 1.0))
        return [
            CityLearnViolation(
                type="peak",
                building_id=None,
                severity=round(severity, 3),
                current_value=round(stats.current_load, 3),
                limit_value=PEAK_THRESHOLD_KWH,
                description=f"District net load {stats.current_load:.2f} kWh가 peak 임계값 {PEAK_THRESHOLD_KWH} kWh를 초과",
            )
        ]

    @staticmethod
    def _ramping(stats: _DistrictStats) -> List[CityLearnViolation]:
        if stats.previous_load is None:
            return []
        delta = abs(stats.current_load - stats.previous_load)
        if delta <= RAMP_THRESHOLD_KWH:
            return []
        severity = min(1.0, (delta - RAMP_THRESHOLD_KWH) / max(RAMP_THRESHOLD_KWH, 1.0))
        return [
            CityLearnViolation(
                type="ramping",
                building_id=None,
                severity=round(severity, 3),
                current_value=round(delta, 3),
                limit_value=RAMP_THRESHOLD_KWH,
                description=f"직전 step 대비 district load 변화량 {delta:.2f} kWh가 ramp 임계값 {RAMP_THRESHOLD_KWH} kWh 초과",
            )
        ]

    @staticmethod
    def _soc(topology: TopologySummary) -> List[CityLearnViolation]:
        violations: List[CityLearnViolation] = []
        for asset in topology.controllable_assets:
            soc = asset.battery_soc
            if soc < SOC_HARD_LOWER:
                severity = min(1.0, (SOC_HARD_LOWER - soc) / SOC_HARD_LOWER)
                violations.append(
                    CityLearnViolation(
                        type="soc",
                        building_id=asset.building_id,
                        severity=round(severity, 3),
                        current_value=round(soc, 3),
                        limit_value=SOC_HARD_LOWER,
                        description=f"{asset.building_id} SOC {soc:.2f}가 하한 {SOC_HARD_LOWER} 미만",
                    )
                )
            elif soc > SOC_HARD_UPPER:
                severity = min(1.0, (soc - SOC_HARD_UPPER) / max(1.0 - SOC_HARD_UPPER, 0.01))
                violations.append(
                    CityLearnViolation(
                        type="soc",
                        building_id=asset.building_id,
                        severity=round(severity, 3),
                        current_value=round(soc, 3),
                        limit_value=SOC_HARD_UPPER,
                        description=f"{asset.building_id} SOC {soc:.2f}가 상한 {SOC_HARD_UPPER} 초과",
                    )
                )
        return violations

    @staticmethod
    def _mapping(topology: TopologySummary) -> List[CityLearnViolation]:
        return [
            CityLearnViolation(
                type="mapping",
                building_id=asset.building_id,
                severity=0.4,
                current_value=0.0,
                limit_value=1.0,
                description=f"{asset.building_id}에 할당된 agent가 없음",
            )
            for asset in topology.controllable_assets
            if not asset.has_mapping
        ]

    @staticmethod
    def _invalid_actions(plan: CityLearnPlan, valid_ids: set[str]) -> List[CityLearnViolation]:
        violations: List[CityLearnViolation] = []
        for action in plan.actions:
            if action.building_id not in valid_ids:
                violations.append(
                    CityLearnViolation(
                        type="invalid_action",
                        building_id=action.building_id,
                        severity=1.0,
                        current_value=action.action,
                        limit_value=0.0,
                        description=f"존재하지 않는 building_id={action.building_id}에 대한 action",
                    )
                )
            elif action.action < ACTION_MIN or action.action > ACTION_MAX:
                violations.append(
                    CityLearnViolation(
                        type="invalid_action",
                        building_id=action.building_id,
                        severity=1.0,
                        current_value=action.action,
                        limit_value=ACTION_MAX,
                        description=f"{action.building_id} action {action.action}이 허용 범위 [-1.0, 1.0] 밖",
                    )
                )
        return violations

    @staticmethod
    def _fairness(plan: CityLearnPlan) -> List[CityLearnViolation]:
        magnitudes = [abs(a.action) for a in plan.actions if a.mode != "hold"]
        if len(magnitudes) < 2:
            return []
        std = _stddev(magnitudes)
        if std <= FAIRNESS_STD_THRESHOLD:
            return []
        return [
            CityLearnViolation(
                type="fairness",
                building_id=None,
                severity=min(1.0, std / max(FAIRNESS_STD_THRESHOLD, 0.01)),
                current_value=round(std, 3),
                limit_value=FAIRNESS_STD_THRESHOLD,
                description=f"plan 내 |action| 표준편차 {std:.2f}가 fairness 임계값 {FAIRNESS_STD_THRESHOLD} 초과",
            )
        ]


def _district_stats(snapshot: Mapping[str, Any]) -> _DistrictStats:
    """district level current/previous load 산출."""
    buildings = snapshot.get("buildings", [])
    current = sum(float(b.get("agent_mesh_net_load_kwh", b.get("net_load_kwh", 0.0))) for b in buildings)
    points = list(snapshot.get("points", []))
    previous: Optional[float] = None
    if len(points) >= 2:
        previous = float(points[-2].get("agent_mesh", points[-2].get("baseline", 0.0)))
    return _DistrictStats(current_load=current, previous_load=previous)


# ── HeuristicPlanner ────────────────────────────────────────────────


class HeuristicPlanner:
    """SOC + net load 기반 결정적 plan 생성기."""

    def propose(
        self,
        *,
        topology: TopologySummary,
        violations: Sequence[CityLearnViolation],
        forbidden_action_keys: Iterable[str] = (),
    ) -> CityLearnPlan:
        forbidden = set(forbidden_action_keys)
        peak_present = any(v.type == "peak" for v in violations)
        actions: List[CityLearnAction] = []

        for asset in topology.controllable_assets:
            action_value, mode, reason, effect = _decide_action(asset, peak_present)
            if action_value == 0.0:
                continue

            key = _action_key(asset.building_id, action_value)
            if key in forbidden:
                continue

            actions.append(
                CityLearnAction(
                    building_id=asset.building_id,
                    action=action_value,
                    mode=mode,
                    reason=reason,
                    expected_effect=effect,
                    confidence=HEURISTIC_CONFIDENCE if asset.has_mapping else HEURISTIC_CONFIDENCE / 2,
                )
            )

        strategy = "피크 시간대 고부하 빌딩 방전 + 저부하 빌딩 충전" if peak_present else "SOC 회복 위주의 보수적 충방전"
        risk = (
            f"방전 후보 {sum(1 for a in actions if a.mode == 'discharge')}개, "
            f"충전 후보 {sum(1 for a in actions if a.mode == 'charge')}개. "
            "SOC soft bound 보호 우선."
        )
        return CityLearnPlan(strategy_summary=strategy, actions=actions, risk_assessment=risk)


def _decide_action(asset: ControllableAsset, peak_present: bool) -> Tuple[float, ActionMode, str, str]:
    """단일 building에 대한 결정 규칙. (action, mode, reason, expected_effect) 반환."""
    soc = asset.battery_soc
    net = asset.net_load_kwh

    if soc <= SOC_SOFT_LOWER:
        if net <= BUILDING_LOW_LOAD_KWH and soc < SOC_SOFT_UPPER:
            return (
                HEURISTIC_CHARGE_ACTION,
                "charge",
                f"SOC {soc:.2f}가 soft lower {SOC_SOFT_LOWER} 이하이고 net load {net:.2f}kWh가 낮아 충전",
                f"+{HEURISTIC_CHARGE_ACTION * SOC_DELTA_PER_UNIT_ACTION:.2f} SOC 회복",
            )
        return 0.0, "hold", f"SOC {soc:.2f}가 soft lower 이하이므로 방전 금지, 충전 여력 없음", "동작 없음"

    if soc >= SOC_SOFT_UPPER:
        if net >= BUILDING_HIGH_LOAD_KWH:
            return (
                HEURISTIC_DISCHARGE_ACTION,
                "discharge",
                f"SOC {soc:.2f}가 soft upper {SOC_SOFT_UPPER} 이상이고 net load {net:.2f}kWh로 방전 적합",
                f"{HEURISTIC_DISCHARGE_ACTION * BATTERY_POWER_KWH:.2f}kWh net load 감소",
            )
        return 0.0, "hold", f"SOC {soc:.2f}가 soft upper 이상이므로 충전 금지", "동작 없음"

    if peak_present and net >= BUILDING_HIGH_LOAD_KWH:
        return (
            HEURISTIC_DISCHARGE_ACTION,
            "discharge",
            f"district peak 진행 중이며 net load {net:.2f}kWh가 BUILDING_HIGH_LOAD_KWH={BUILDING_HIGH_LOAD_KWH} 이상",
            f"{HEURISTIC_DISCHARGE_ACTION * BATTERY_POWER_KWH:.2f}kWh net load 감소",
        )
    if net <= BUILDING_LOW_LOAD_KWH and soc < SOC_SOFT_UPPER:
        return (
            HEURISTIC_CHARGE_ACTION * 0.5,
            "charge",
            f"net load {net:.2f}kWh가 낮고 SOC {soc:.2f}로 여유 있음",
            "소량 충전으로 다음 피크 대비",
        )
    return 0.0, "hold", "현재 상태에서 추가 action 불필요", "동작 없음"


# ── SandboxExecutor ─────────────────────────────────────────────────


class SandboxExecutor:
    """deepcopy 후 plan을 적용한 새 snapshot 반환. 원본은 절대 변경하지 않는다."""

    def execute(
        self,
        *,
        snapshot: Mapping[str, Any],
        plan: CityLearnPlan,
    ) -> Dict[str, Any]:
        sandbox = copy.deepcopy(dict(snapshot))
        action_by_building = {a.building_id: a for a in plan.actions}

        for building in sandbox.get("buildings", []):
            building_id = building.get("building_id")
            action = action_by_building.get(building_id)
            if not action:
                continue
            building["battery_soc"] = round(
                max(UNIT_MIN, min(UNIT_MAX, float(building.get("battery_soc", 0.5)) + action.action * SOC_DELTA_PER_UNIT_ACTION)),
                3,
            )
            new_net = float(building.get("agent_mesh_net_load_kwh", 0.0)) + action.action * BATTERY_POWER_KWH
            new_net = max(0.0, new_net)
            building["agent_mesh_net_load_kwh"] = round(new_net, 3)
            building["net_load_kwh"] = round(new_net, 3)
            building["battery_action"] = (
                "charging" if action.mode == "charge"
                else "discharging" if action.mode == "discharge"
                else "idle"
            )

        # points 마지막 entry의 agent_mesh를 sandbox district load로 갱신 (ramping 재계산용).
        points = sandbox.get("points")
        if isinstance(points, list) and points:
            new_district = sum(
                float(b.get("agent_mesh_net_load_kwh", 0.0))
                for b in sandbox.get("buildings", [])
            )
            points[-1] = {**points[-1], "agent_mesh": round(new_district, 3)}

        return sandbox


# ── ConstraintValidator ─────────────────────────────────────────────


class ConstraintValidator:
    """score_before/after 비교 + new_violations 산출 + approved 결정."""

    def validate(
        self,
        *,
        snapshot_before: Mapping[str, Any],
        snapshot_after: Mapping[str, Any],
        topology_before: TopologySummary,
        topology_after: TopologySummary,
        plan: CityLearnPlan,
        initial_violations: Sequence[CityLearnViolation],
        forbidden_action_keys: Iterable[str] = (),
    ) -> CityLearnValidationResult:
        valid_building_ids = {a.building_id for a in topology_after.controllable_assets}

        post_detector = ViolationDetector()
        post_violations = post_detector.detect_post_action(
            sandbox_snapshot=snapshot_after,
            sandbox_topology=topology_after,
            plan=plan,
            valid_building_ids=valid_building_ids,
        )

        score_before = _score(snapshot_before, topology_before, plan_actions=())
        score_after = _score(snapshot_after, topology_after, plan_actions=plan.actions)

        initial_keys = {(v.type, v.building_id) for v in initial_violations}
        new_violations = [v for v in post_violations if (v.type, v.building_id) not in initial_keys]
        resolved_violations = [
            v for v in initial_violations
            if (v.type, v.building_id) not in {(p.type, p.building_id) for p in post_violations}
        ]
        remaining_violations = [
            v for v in initial_violations
            if (v.type, v.building_id) in {(p.type, p.building_id) for p in post_violations}
        ]

        # invalid_action / new SOC violation 발생 시 무조건 reject.
        hard_block = any(v.type in {"invalid_action", "soc"} for v in new_violations)

        improved = score_after < score_before
        approved = improved and not hard_block

        clipped_actions = [
            CityLearnAction(
                building_id=a.building_id,
                action=_clip_action(a.action),
                mode=_classify_mode(_clip_action(a.action)),
                reason=a.reason,
                expected_effect=a.expected_effect,
                confidence=a.confidence,
            )
            for a in plan.actions
            if a.action < ACTION_MIN or a.action > ACTION_MAX
        ]

        accumulated_forbidden = list(dict.fromkeys(
            list(forbidden_action_keys)
            + ([_action_key(a.building_id, a.action) for a in plan.actions] if not approved else [])
        ))

        feedback = _build_feedback(
            approved=approved,
            improved=improved,
            score_before=score_before,
            score_after=score_after,
            new_violations=new_violations,
            hard_block=hard_block,
        )

        return CityLearnValidationResult(
            approved=approved,
            status="approved" if approved else "rejected",
            score_before=round(score_before, 3),
            score_after=round(score_after, 3),
            resolved_violations=resolved_violations,
            remaining_violations=remaining_violations,
            new_violations=new_violations,
            clipped_actions=clipped_actions,
            forbidden_action_keys=accumulated_forbidden,
            feedback=feedback,
        )


def _score(
    snapshot: Mapping[str, Any],
    topology: TopologySummary,
    *,
    plan_actions: Sequence[CityLearnAction],
) -> float:
    """docs/architecture/01_paper_grid_agent.md §7 scoring 공식."""
    stats = _district_stats(snapshot)
    district_load = stats.current_load

    soc_penalty = SOC_PENALTY_PER_BUILDING * sum(
        1 for asset in topology.controllable_assets
        if asset.battery_soc < SOC_HARD_LOWER or asset.battery_soc > SOC_HARD_UPPER
    )
    peak_penalty = max(0.0, district_load - PEAK_THRESHOLD_KWH) * PEAK_PENALTY_WEIGHT
    if stats.previous_load is not None:
        ramp = max(0.0, abs(district_load - stats.previous_load) - RAMP_THRESHOLD_KWH)
    else:
        ramp = 0.0
    ramp_penalty = ramp * RAMP_PENALTY_WEIGHT
    magnitudes = [abs(a.action) for a in plan_actions]
    fairness_penalty = _stddev(magnitudes) * FAIRNESS_PENALTY_WEIGHT
    return district_load + soc_penalty + peak_penalty + ramp_penalty + fairness_penalty


def _build_feedback(
    *,
    approved: bool,
    improved: bool,
    score_before: float,
    score_after: float,
    new_violations: Sequence[CityLearnViolation],
    hard_block: bool,
) -> str:
    if approved:
        return f"승인: score {score_before:.2f} → {score_after:.2f}, 새 violation 없음."
    parts: List[str] = []
    if not improved:
        parts.append(f"score 미개선 ({score_before:.2f} → {score_after:.2f})")
    if hard_block:
        for v in new_violations:
            if v.type in {"invalid_action", "soc"}:
                parts.append(f"새 {v.type} violation: {v.description}")
    if not parts:
        parts.append("기타 사유로 reject")
    return "거절: " + "; ".join(parts)


# ── OperatorSummarizer ──────────────────────────────────────────────


class OperatorSummarizer:
    """Template 기반 한국어 운영자 요약. Phase 2부터 LLM으로 대체될 수 있다."""

    def summarize(
        self,
        *,
        topology: TopologySummary,
        plan: CityLearnPlan,
        validation: CityLearnValidationResult,
        initial_violations: Sequence[CityLearnViolation],
    ) -> str:
        violation_summary = (
            ", ".join(sorted({v.type for v in initial_violations}))
            if initial_violations
            else "없음"
        )
        action_count = len(plan.actions)
        discharge_count = sum(1 for a in plan.actions if a.mode == "discharge")
        charge_count = sum(1 for a in plan.actions if a.mode == "charge")
        status_kr = "승인됨" if validation.approved else "거절됨"

        lines = [
            f"[Grid-Agent step {topology.step}] {status_kr} · 빌딩 {topology.building_count}개 (매핑 {topology.mapped_building_count}개).",
            f"초기 violation: {violation_summary}.",
            f"제안 action: 총 {action_count}건 (방전 {discharge_count} / 충전 {charge_count}).",
            f"District score: {validation.score_before:.2f} → {validation.score_after:.2f}.",
            validation.feedback,
        ]
        return " ".join(lines)


# ── Orchestrator (편의 함수) ────────────────────────────────────────


@dataclass
class GridAgentRunResult:
    """analyze + plan + validate를 한 번에 돌린 결과 컨테이너."""

    topology: TopologySummary
    initial_violations: List[CityLearnViolation]
    final_plan: CityLearnPlan
    validation: CityLearnValidationResult
    operator_summary: str
    requested_at: datetime
    iterations: List["PlanIteration"] = field(default_factory=list)


def run_deterministic_plan(
    *,
    workspace_id: UUID,
    snapshot: Mapping[str, Any],
    mapping: Optional[Mapping[str, Any]],
    forbidden_action_keys: Iterable[str] = (),
    baseline_model: Optional[BaselineModel] = None,
    agent_mesh_mode: Optional[AgentMeshMode] = None,
) -> GridAgentRunResult:
    """Phase 1 deterministic 파이프라인을 한 번에 실행한다.

    API layer (AM-api-001)와 unit test 양쪽에서 호출하기 좋은 편의 함수.
    baseline_model/agent_mesh_mode를 명시하면 snapshot inference보다 우선 적용된다 (AM-ui-001).
    """
    analyzer = TopologyAnalyzer()
    detector = ViolationDetector()
    planner = HeuristicPlanner()
    executor = SandboxExecutor()
    validator = ConstraintValidator()
    summarizer = OperatorSummarizer()

    topology_before = analyzer.analyze(
        workspace_id=workspace_id,
        snapshot=snapshot,
        mapping=mapping,
        baseline_model=baseline_model,
        agent_mesh_mode=agent_mesh_mode,
    )
    initial_violations = detector.detect_initial(topology=topology_before, snapshot=snapshot)

    plan = planner.propose(
        topology=topology_before,
        violations=initial_violations,
        forbidden_action_keys=forbidden_action_keys,
    )

    sandbox_snapshot = executor.execute(snapshot=snapshot, plan=plan)
    topology_after = analyzer.analyze(
        workspace_id=workspace_id,
        snapshot=sandbox_snapshot,
        mapping=mapping,
        baseline_model=baseline_model,
        agent_mesh_mode=agent_mesh_mode,
    )

    validation = validator.validate(
        snapshot_before=snapshot,
        snapshot_after=sandbox_snapshot,
        topology_before=topology_before,
        topology_after=topology_after,
        plan=plan,
        initial_violations=initial_violations,
        forbidden_action_keys=forbidden_action_keys,
    )

    operator_summary = summarizer.summarize(
        topology=topology_before,
        plan=plan,
        validation=validation,
        initial_violations=initial_violations,
    )

    return GridAgentRunResult(
        topology=topology_before,
        initial_violations=initial_violations,
        final_plan=plan,
        validation=validation,
        operator_summary=operator_summary,
        requested_at=datetime.now(timezone.utc),
    )


__all__ = [
    "ConstraintValidator",
    "GridAgentRunResult",
    "HeuristicPlanner",
    "OperatorSummarizer",
    "SandboxExecutor",
    "TopologyAnalyzer",
    "ViolationDetector",
    "run_deterministic_plan",
]

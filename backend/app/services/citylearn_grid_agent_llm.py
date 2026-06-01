"""Grid-Agent LLM Planner replanning loop (AM-llm-001).

Phase 2 LLM Planner 통합 — City Grid Coordinator agent를 매 iteration마다 invoke해
validate를 통과하는 plan을 얻을 때까지 forbidden_action_keys를 누적하며 재시도한다.

핵심 안전 원칙
- LLM 출력은 무조건 schema(JSON) + sandbox 검증 통과 필수.
- LLM call 실패 / API 키 없음 / parsing 실패 시 HeuristicPlanner fallback.
- 검증 실패 plan의 action key는 forbidden_action_keys에 누적되어 다음 prompt에 재주입된다.
- iterations[]에 모든 시도(approved/rejected/fallback)가 trace로 보존된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
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
    PlanIteration,
    TopologySummary,
)
from app.services.agent_runtime import invoke_agent
from app.services.citylearn_grid_agent import (
    ConstraintValidator,
    GridAgentRunResult,
    HeuristicPlanner,
    OperatorSummarizer,
    SandboxExecutor,
    TopologyAnalyzer,
    ViolationDetector,
)
from app.services.citylearn_grid_agent_constants import HEURISTIC_CONFIDENCE


logger = logging.getLogger(__name__)


COORDINATOR_AGENT_NAME = "City Grid Coordinator"

# 한 step의 LLM 응답 예산. Sonnet 4.6 Coordinator는 단일 호출이라 60s면 충분하지만,
# MACRO-Mesh 17 building 병렬 협상이 ~4분 걸리므로 360s로 통일 (frontend timeout과 일치).
LLM_INVOKE_TIMEOUT_SECONDS = 360.0


async def load_coordinator_agent(db: Optional[AsyncSession]) -> Optional[Agent]:
    """seed된 City Grid Coordinator agent를 DB에서 조회한다.

    db가 None이거나 lookup이 실패하면 None을 반환해 heuristic fallback을 유도한다.
    """
    if db is None:
        return None
    try:
        result = await db.execute(select(Agent).where(Agent.name == COORDINATOR_AGENT_NAME))
        return result.scalars().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("AM-llm-001: coordinator agent lookup failed: %s", exc)
        return None


async def publish_plan_message(
    *,
    db: Optional[AsyncSession],
    workspace_id: UUID,
    run_result: GridAgentRunResult,
    used_llm_planner: bool,
    step: int,
) -> bool:
    """plan 결과를 여러 메시지로 펼쳐 워크스페이스 피드에 발행한다.

    한 번의 plan API 호출이 5~N개의 메시지로 분해되어 timeline에 노출된다:
      1. plan_start: 시작 알림 + initial_violations 목록
      2. tool_call × M: 각 도구 호출 (tool name + args 요약, iteration별)
      3. iter_result × K: 각 iteration의 결과 (approved/rejected/schema_failed)
      4. plan_result: 전체 요약 + operator_summary

    - Coordinator agent가 워크스페이스에 배치되어 있어야 sender_type='agent', 없으면 'system'
    - 실패는 plan API의 본 응답을 막지 않는다 (silent skip + rollback)
    """
    if db is None:
        return False

    from app.models.message import Message, MessageHeader
    from app.models.workspace import WorkspaceAgent
    from app.services.message_broker import build_inline_body_ref

    coord = None
    sender_type = "agent" if used_llm_planner else "system"
    try:
        coord = await load_coordinator_agent(db)
        if coord is not None:
            placed = (
                await db.execute(
                    select(WorkspaceAgent).where(
                        WorkspaceAgent.workspace_id == workspace_id,
                        WorkspaceAgent.agent_id == coord.agent_id,
                    )
                )
            ).scalars().first()
            if placed is None:
                coord = None
                sender_type = "system"
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_plan_message: coordinator lookup failed: %s", exc)
        coord = None
        sender_type = "system"

    sender_id = coord.agent_id if coord else workspace_id
    sender_name = coord.name if coord else "Grid-Agent System"

    def _add(*, intent: str, kind: str, message: str, extras: dict, tags: list) -> None:
        body = {
            "kind": kind,
            "step": step,
            "message": message,
            "used_llm_planner": used_llm_planner,
            **extras,
        }
        body_ref = build_inline_body_ref(body)
        db.add(
            MessageHeader(
                sender_id=sender_id, sender_type=sender_type, sender_name=sender_name,
                domain="grid_agent", intent=intent, priority="medium",
                tags=["grid_agent", *tags],
                target_ids=[], target_roles=[],
                scope="workspace", workspace_id=workspace_id,
                body_ref=body_ref, processed_count=0,
            )
        )
        db.add(
            Message(
                workspace_id=workspace_id,
                participant_id=sender_id, participant_type=sender_type,
                content=body_ref,
            )
        )

    try:
        # 1) plan_start
        planner_mode_label = "LLM Planner" if used_llm_planner else "Heuristic only"
        _add(
            intent="plan_start", kind="grid_agent_plan_start",
            message=f"[Step {step + 1}] {planner_mode_label} 시작 — 17 building 분석",
            extras={
                "iteration_count": len(run_result.iterations) or 1,
                "initial_violations": [
                    {"type": v.type, "building_id": v.building_id, "description": v.description}
                    for v in run_result.initial_violations[:10]
                ],
            },
            tags=["plan", "start"],
        )

        # 2) iteration별 tool calls + result
        for it in run_result.iterations:
            po = it.planner_output or {}
            tool_calls = po.get("tool_calls", []) if isinstance(po, dict) else []
            for idx, tc in enumerate(tool_calls):
                tname = tc.get("name") if isinstance(tc, dict) else "?"
                targs = tc.get("args") if isinstance(tc, dict) else {}
                args_preview = (str(targs)[:120]) if targs else "(no args)"
                _add(
                    intent="tool_call", kind="grid_agent_tool_call",
                    message=f"[Step {step + 1}][iter {it.iteration}.{idx + 1}] 도구 호출: {tname}({args_preview})",
                    extras={"iteration": it.iteration, "tool_name": tname, "tool_args": targs},
                    tags=["tool_call", str(tname)],
                )

            iter_msg = (
                f"[Step {step + 1}][iter {it.iteration}] {it.route_decision or '-'} "
                f"· score {it.validation.score_before:.2f}→{it.validation.score_after:.2f} "
                f"· actions {len(it.plan.actions)}"
            )
            _add(
                intent="iter_result", kind="grid_agent_iter_result",
                message=iter_msg,
                extras={
                    "iteration": it.iteration,
                    "planner_kind": it.planner_kind,
                    "approved": it.validation.approved,
                    "route_decision": it.route_decision,
                    "score_before": round(it.validation.score_before, 2),
                    "score_after": round(it.validation.score_after, 2),
                    "actions": [
                        {"building_id": a.building_id, "action": round(a.action, 3), "mode": a.mode}
                        for a in it.plan.actions
                    ],
                    "feedback": it.validation.feedback,
                },
                tags=["iter", it.planner_kind, "approved" if it.validation.approved else "rejected"],
            )

        # 3) plan_result (final summary)
        final_msg = (
            f"[Step {step + 1}] {'승인' if run_result.validation.approved else '거절'} "
            f"· score {run_result.validation.score_before:.2f}→{run_result.validation.score_after:.2f} "
            f"· actions {len(run_result.final_plan.actions)}"
        )
        _add(
            intent="plan_result", kind="grid_agent_plan",
            message=final_msg,
            extras={
                "approved": run_result.validation.approved,
                "status": run_result.validation.status,
                "score_before": round(run_result.validation.score_before, 2),
                "score_after": round(run_result.validation.score_after, 2),
                "operator_summary": run_result.operator_summary,
                "actions": [
                    {
                        "building_id": a.building_id, "action": round(a.action, 3),
                        "mode": a.mode, "confidence": round(a.confidence, 3), "reason": a.reason,
                    }
                    for a in run_result.final_plan.actions[:17]
                ],
                "feedback": run_result.validation.feedback,
            },
            tags=["plan", "approved" if run_result.validation.approved else "rejected"],
        )

        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_plan_message: insert failed (skipping): %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def _build_planner_prompt(
    *,
    step: int,
    topology: TopologySummary,
    initial_violations: Sequence[CityLearnViolation],
    forbidden_action_keys: Sequence[str],
    last_validation: Optional[CityLearnValidationResult],
    iteration: int,
) -> str:
    """LLM Coordinator에게 매 iteration 보낼 user 메시지."""
    asset_summary = [
        {
            "building_id": a.building_id,
            "battery_soc": round(a.battery_soc, 3),
            "net_load_kwh": round(a.net_load_kwh, 3),
            "pv_kwh": round(a.pv_generation_kwh, 3),
            "has_agent": a.has_mapping,
        }
        for a in topology.controllable_assets
    ]
    violations = [
        {"type": v.type, "building_id": v.building_id, "severity": v.severity, "desc": v.description}
        for v in initial_violations
    ]
    feedback_block: Dict[str, Any] = {}
    if last_validation is not None:
        feedback_block = {
            "previous_approved": last_validation.approved,
            "score_before": last_validation.score_before,
            "score_after": last_validation.score_after,
            "feedback": last_validation.feedback,
            "new_violations": [
                {"type": v.type, "building_id": v.building_id} for v in last_validation.new_violations
            ],
        }

    payload = {
        "task": "propose_battery_plan",
        "iteration": iteration,
        "step": step,
        "district_net_load_kwh": topology.district_net_load_kwh,
        "controllable_assets": asset_summary,
        "initial_violations": violations,
        "forbidden_action_keys": list(forbidden_action_keys),
        "previous_attempt": feedback_block,
        "instructions": (
            "validate_citylearn_battery_plan을 반드시 호출해 sandbox 검증을 통과시키고, "
            "최종 응답은 {\"strategy_summary\":...,\"actions\":[{building_id,action,mode,reason,expected_effect,confidence}],\"risk_assessment\":...} "
            "JSON을 final answer로 반환하십시오. forbidden_action_keys 목록의 키는 그대로 반복 금지."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_llm_plan(raw_output: str, valid_building_ids: set[str]) -> Optional[CityLearnPlan]:
    """LLM final answer를 CityLearnPlan으로 파싱. 실패 시 None."""
    if not raw_output:
        return None
    text = raw_output.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 텍스트 안에 JSON object가 묻혀있으면 첫 번째만 시도.
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None
    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list):
        return None

    parsed_actions: List[CityLearnAction] = []
    for raw in raw_actions:
        if not isinstance(raw, dict):
            return None
        # 누락 필드는 안전한 기본값으로 채워 schema 통과시키되, building_id/action은 필수.
        building_id = raw.get("building_id")
        if not isinstance(building_id, str) or building_id not in valid_building_ids:
            return None
        try:
            action_value = float(raw.get("action"))
        except (TypeError, ValueError):
            return None
        if action_value < -1.0 or action_value > 1.0:
            return None
        mode = raw.get("mode") if raw.get("mode") in {"charge", "discharge", "hold"} else (
            "charge" if action_value > 0.05 else "discharge" if action_value < -0.05 else "hold"
        )
        try:
            confidence = float(raw.get("confidence", HEURISTIC_CONFIDENCE))
        except (TypeError, ValueError):
            confidence = HEURISTIC_CONFIDENCE
        confidence = max(0.0, min(1.0, confidence))

        parsed_actions.append(
            CityLearnAction(
                building_id=building_id,
                action=action_value,
                mode=mode,
                reason=str(raw.get("reason") or "LLM proposal"),
                expected_effect=str(raw.get("expected_effect") or ""),
                confidence=confidence,
            )
        )

    return CityLearnPlan(
        strategy_summary=str(data.get("strategy_summary") or "LLM plan"),
        actions=parsed_actions,
        risk_assessment=str(data.get("risk_assessment") or ""),
    )


def _heuristic_fallback_result(
    *,
    workspace_id: UUID,
    snapshot: Mapping[str, Any],
    mapping: Optional[Mapping[str, Any]],
    baseline_model: Optional[BaselineModel],
    agent_mesh_mode: Optional[AgentMeshMode],
    forbidden_action_keys: Sequence[str],
    iterations: List[PlanIteration],
    fallback_reason: str,
) -> GridAgentRunResult:
    """LLM 호출이 불가능할 때 deterministic 엔진으로 한 번 더 시도해 최종 결과를 만든다."""
    analyzer = TopologyAnalyzer()
    detector = ViolationDetector()
    planner = HeuristicPlanner()
    executor = SandboxExecutor()
    validator = ConstraintValidator()
    summarizer = OperatorSummarizer()

    topology_before = analyzer.analyze(
        workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    initial_violations = detector.detect_initial(topology=topology_before, snapshot=snapshot)
    plan = planner.propose(
        topology=topology_before,
        violations=initial_violations,
        forbidden_action_keys=forbidden_action_keys,
    )
    sandbox = executor.execute(snapshot=snapshot, plan=plan)
    topology_after = analyzer.analyze(
        workspace_id=workspace_id, snapshot=sandbox, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    validation = validator.validate(
        snapshot_before=snapshot, snapshot_after=sandbox,
        topology_before=topology_before, topology_after=topology_after,
        plan=plan, initial_violations=initial_violations,
        forbidden_action_keys=forbidden_action_keys,
    )

    iterations.append(
        PlanIteration(
            iteration=len(iterations) + 1,
            planner_kind="heuristic",
            planner_output={"fallback_reason": fallback_reason},
            plan=plan,
            validation=validation,
            route_decision=f"fallback ({fallback_reason})",
        )
    )

    return GridAgentRunResult(
        topology=topology_before,
        initial_violations=initial_violations,
        final_plan=plan,
        validation=validation,
        operator_summary=summarizer.summarize(
            topology=topology_before, plan=plan,
            validation=validation, initial_violations=initial_violations,
        ),
        requested_at=datetime.now(timezone.utc),
        iterations=iterations,
    )


async def run_llm_planner_loop(
    *,
    db: AsyncSession,
    workspace_id: UUID,
    snapshot: Mapping[str, Any],
    mapping: Optional[Mapping[str, Any]],
    baseline_model: Optional[BaselineModel],
    agent_mesh_mode: Optional[AgentMeshMode],
    max_iterations: int = 3,
    initial_forbidden_keys: Iterable[str] = (),
    model: Optional[str] = None,
) -> GridAgentRunResult:
    """LLM Planner replanning loop.

    매 iteration마다 City Grid Coordinator agent를 invoke해 plan을 받고,
    SandboxExecutor + ConstraintValidator로 재검증한다.
    검증 실패 시 forbidden_action_keys를 누적해 다음 prompt에 주입한다.
    """
    analyzer = TopologyAnalyzer()
    detector = ViolationDetector()
    executor = SandboxExecutor()
    validator = ConstraintValidator()
    summarizer = OperatorSummarizer()

    coordinator = await load_coordinator_agent(db)
    iterations: List[PlanIteration] = []
    forbidden_keys: List[str] = list(initial_forbidden_keys)

    if coordinator is None:
        logger.warning("AM-llm-001: City Grid Coordinator agent not seeded, falling back to heuristic.")
        return _heuristic_fallback_result(
            workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
            baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
            forbidden_action_keys=forbidden_keys, iterations=iterations,
            fallback_reason="coordinator_agent_not_seeded",
        )

    topology_before = analyzer.analyze(
        workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
        baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
    )
    initial_violations = detector.detect_initial(topology=topology_before, snapshot=snapshot)
    valid_building_ids = {a.building_id for a in topology_before.controllable_assets}

    last_validation: Optional[CityLearnValidationResult] = None
    last_plan: Optional[CityLearnPlan] = None
    topology_after: TopologySummary = topology_before

    for iteration in range(1, max_iterations + 1):
        prompt = _build_planner_prompt(
            step=topology_before.step,
            topology=topology_before,
            initial_violations=initial_violations,
            forbidden_action_keys=forbidden_keys,
            last_validation=last_validation,
            iteration=iteration,
        )

        try:
            invoke_result = await asyncio.wait_for(
                invoke_agent(agent=coordinator, user_message=prompt, model=model),
                timeout=LLM_INVOKE_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, RuntimeError, Exception) as exc:  # noqa: BLE001
            logger.warning("AM-llm-001: LLM invoke failed at iteration %d: %s", iteration, exc)
            return _heuristic_fallback_result(
                workspace_id=workspace_id, snapshot=snapshot, mapping=mapping,
                baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
                forbidden_action_keys=forbidden_keys, iterations=iterations,
                fallback_reason=f"llm_invoke_error: {type(exc).__name__}",
            )

        raw_output = str(invoke_result.get("output") or "")
        plan = _parse_llm_plan(raw_output, valid_building_ids)

        if plan is None:
            iterations.append(
                PlanIteration(
                    iteration=iteration, planner_kind="llm",
                    planner_output={"raw_output": raw_output[:1000], "tool_calls": invoke_result.get("tool_calls", [])},
                    plan=CityLearnPlan(strategy_summary="(schema failed)", actions=[], risk_assessment="parsing failed"),
                    validation=CityLearnValidationResult(
                        approved=False, status="rejected",
                        score_before=0.0, score_after=0.0,
                        resolved_violations=[], remaining_violations=[], new_violations=[],
                        clipped_actions=[], forbidden_action_keys=forbidden_keys,
                        feedback="LLM final answer를 JSON action 배열로 파싱할 수 없습니다.",
                    ),
                    route_decision="reject (schema_failed)",
                )
            )
            continue

        sandbox = executor.execute(snapshot=snapshot, plan=plan)
        topology_after = analyzer.analyze(
            workspace_id=workspace_id, snapshot=sandbox, mapping=mapping,
            baseline_model=baseline_model, agent_mesh_mode=agent_mesh_mode,
        )
        validation = validator.validate(
            snapshot_before=snapshot, snapshot_after=sandbox,
            topology_before=topology_before, topology_after=topology_after,
            plan=plan, initial_violations=initial_violations,
            forbidden_action_keys=forbidden_keys,
        )

        iterations.append(
            PlanIteration(
                iteration=iteration, planner_kind="llm",
                planner_output={
                    "tool_calls": invoke_result.get("tool_calls", []),
                    "model_used": invoke_result.get("model_used"),
                    "raw_output_preview": raw_output[:400],
                },
                plan=plan, validation=validation,
                route_decision="approved" if validation.approved else "reject (validation_failed)",
            )
        )

        forbidden_keys = list(validation.forbidden_action_keys)
        last_validation = validation
        last_plan = plan

        if validation.approved:
            return GridAgentRunResult(
                topology=topology_before,
                initial_violations=initial_violations,
                final_plan=plan,
                validation=validation,
                operator_summary=summarizer.summarize(
                    topology=topology_before, plan=plan,
                    validation=validation, initial_violations=initial_violations,
                ),
                requested_at=datetime.now(timezone.utc),
                iterations=iterations,
            )

    # max_iterations 도달 — 마지막 시도 결과를 그대로 반환.
    final_plan = last_plan or CityLearnPlan(strategy_summary="(no plan)", actions=[], risk_assessment="max iterations exhausted")
    final_validation = last_validation or CityLearnValidationResult(
        approved=False, status="rejected",
        score_before=0.0, score_after=0.0,
        resolved_violations=[], remaining_violations=[], new_violations=[],
        clipped_actions=[], forbidden_action_keys=forbidden_keys,
        feedback=f"max_iterations={max_iterations} 도달, 승인된 plan 없음.",
    )
    return GridAgentRunResult(
        topology=topology_before,
        initial_violations=initial_violations,
        final_plan=final_plan,
        validation=final_validation,
        operator_summary=summarizer.summarize(
            topology=topology_before, plan=final_plan,
            validation=final_validation, initial_violations=initial_violations,
        ),
        requested_at=datetime.now(timezone.utc),
        iterations=iterations,
    )


__all__ = [
    "COORDINATOR_AGENT_NAME",
    "LLM_INVOKE_TIMEOUT_SECONDS",
    "load_coordinator_agent",
    "run_llm_planner_loop",
]

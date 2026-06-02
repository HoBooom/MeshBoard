"""CityLearn board runtime + Grid-Agent endpoints.

Grid-Agent (AM-api-001): preview-only POST endpoints that join board snapshots with
workspace.metadata_.agent_building_mapping and run the deterministic Phase 1 engine.
DB commit은 Phase 4 (AM-log-001)에서 별도 endpoint로 분리한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.workspaces import _ensure_access
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.citylearn_grid_agent import (
    GridAgentAnalyzeRequest,
    GridAgentAnalyzeResponse,
    GridAgentPlanRequest,
    GridAgentPlanResponse,
    PlanIteration,
)
from app.schemas.citylearn_macro_mesh import (
    MacroMeshNegotiateRequest,
    MacroMeshNegotiateResponse,
)
from app.services.citylearn_board import get_board_snapshot
from app.services.citylearn_grid_agent import run_deterministic_plan
from app.services.citylearn_grid_agent_llm import publish_plan_message, run_llm_planner_loop
from app.services.citylearn_macro_mesh import run_macro_mesh_negotiation
from app.services.citylearn_macro_mesh_v2 import run_macro_mesh_v2_negotiation


router = APIRouter(prefix="/citylearn", tags=["citylearn"])

BaselineModel = Literal["basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"]
AgentMeshMode = Literal[
    "not_configured",
    "demo_heuristic",
    "configured_agents",
    "grid_agent",
    "macro_mesh",
    "macro_mesh_v2",
]


@router.get("/board")
async def citylearn_board_snapshot(
    step: int = Query(0, ge=0, le=8759),
    baseline_model: BaselineModel = "sacrbc",
    agent_mesh_mode: AgentMeshMode = "not_configured",
    window: int = Query(72, ge=1, le=168),
    _: User = Depends(get_current_user),
):
    return get_board_snapshot(
        step=step,
        baseline_model=baseline_model,
        agent_mesh_mode=agent_mesh_mode,
        window=window,
    )


# ── Grid-Agent (Phase 1 deterministic, preview-only) ─────────────────


@router.post("/grid-agent/analyze", response_model=GridAgentAnalyzeResponse)
async def citylearn_grid_agent_analyze(
    payload: GridAgentAnalyzeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GridAgentAnalyzeResponse:
    """현재 step의 topology + initial violation을 반환. action은 제안하지 않는다."""
    workspace = await _ensure_access(db, payload.workspace_id, user)

    snapshot = get_board_snapshot(
        step=payload.step,
        baseline_model=payload.baseline_model,
        agent_mesh_mode=payload.agent_mesh_mode,
        window=payload.window,
    )

    try:
        result = run_deterministic_plan(
            workspace_id=workspace.workspace_id,
            snapshot=snapshot,
            mapping=workspace.metadata_,
            baseline_model=payload.baseline_model,
            agent_mesh_mode=payload.agent_mesh_mode,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "runtime_failed", "message": str(exc)},
        ) from exc

    return GridAgentAnalyzeResponse(
        run_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
        topology=result.topology,
        initial_violations=result.initial_violations,
    )


@router.post("/grid-agent/plan", response_model=GridAgentPlanResponse)
async def citylearn_grid_agent_plan(
    payload: GridAgentPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GridAgentPlanResponse:
    """Plan + sandbox validation 결과를 반환. preview-only — DB commit 없음.

    `use_llm_planner=true` (AM-llm-001) 경로:
      - City Grid Coordinator agent를 invoke해 plan을 받고 validate → 실패 시 forbidden_action_keys 누적
      - max_iterations(기본 1, 권장 3)까지 재시도, 모든 시도가 iterations[]에 trace로 노출
      - agent 미시드 / LLM 호출 실패 / parsing 실패 시 HeuristicPlanner fallback (iterations에 그대로 기록)
    """
    workspace = await _ensure_access(db, payload.workspace_id, user)

    snapshot = get_board_snapshot(
        step=payload.step,
        baseline_model=payload.baseline_model,
        agent_mesh_mode=payload.agent_mesh_mode,
        window=payload.window,
    )

    try:
        if payload.use_llm_planner:
            result = await run_llm_planner_loop(
                db=db,
                workspace_id=workspace.workspace_id,
                snapshot=snapshot,
                mapping=workspace.metadata_,
                baseline_model=payload.baseline_model,
                agent_mesh_mode=payload.agent_mesh_mode,
                max_iterations=payload.max_iterations,
                initial_forbidden_keys=payload.forbidden_action_keys,
            )
        else:
            result = run_deterministic_plan(
                workspace_id=workspace.workspace_id,
                snapshot=snapshot,
                mapping=workspace.metadata_,
                forbidden_action_keys=payload.forbidden_action_keys,
                baseline_model=payload.baseline_model,
                agent_mesh_mode=payload.agent_mesh_mode,
            )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "runtime_failed", "message": str(exc)},
        ) from exc

    # AM-ui-001+ : plan 결과를 워크스페이스 메시지 피드에 발행 (실패해도 plan 응답은 그대로).
    await publish_plan_message(
        db=db,
        workspace_id=workspace.workspace_id,
        run_result=result,
        used_llm_planner=payload.use_llm_planner,
        step=payload.step,
    )

    if result.iterations:
        iterations_payload = result.iterations
    else:
        iterations_payload = [
            PlanIteration(
                iteration=1,
                planner_kind="heuristic",
                planner_output=None,
                plan=result.final_plan,
                validation=result.validation,
                route_decision="deterministic",
            )
        ]

    return GridAgentPlanResponse(
        run_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
        topology=result.topology,
        initial_violations=result.initial_violations,
        iterations=iterations_payload,
        final_plan=result.final_plan,
        validation=result.validation,
        operator_summary=result.operator_summary,
        forbidden_action_keys=result.validation.forbidden_action_keys,
    )


# ── MACRO-Mesh 분산 협상 (AM-macro-api-001) ─────────────────────────


@router.post("/macro-mesh/negotiate", response_model=MacroMeshNegotiateResponse)
async def citylearn_macro_mesh_negotiate(
    payload: MacroMeshNegotiateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MacroMeshNegotiateResponse:
    """17 Building Battery Agent의 분산 협상 → Coordinator의 mean_field/conflict 산출 → round 2 재제안.

    `use_llm_proposers=True`: 각 building agent를 LLM으로 invoke (asyncio.gather 병렬, per-building 45s timeout).
    실패한 building은 heuristic fallback으로 개별 대체.
    최종 merged_plan은 Grid-Agent SandboxExecutor + ConstraintValidator로 재검증된다 (preview-only).
    """
    workspace = await _ensure_access(db, payload.workspace_id, user)

    snapshot = get_board_snapshot(
        step=payload.step,
        baseline_model=payload.baseline_model,
        agent_mesh_mode=payload.agent_mesh_mode,
        window=payload.window,
    )

    # macro_mesh_v2: 논문 MACRO-LLM 3모듈 복원판(CoProposer rollout + Introspector).
    # workspace별 전략을 누적해 step 간 temporal reasoning을 유지한다. 반환형은 v1과 동일.
    runner = (
        run_macro_mesh_v2_negotiation
        if payload.agent_mesh_mode == "macro_mesh_v2"
        else run_macro_mesh_negotiation
    )

    try:
        result = await runner(
            db=db,
            workspace_id=workspace.workspace_id,
            snapshot=snapshot,
            mapping=workspace.metadata_,
            baseline_model=payload.baseline_model,
            agent_mesh_mode=payload.agent_mesh_mode,
            max_rounds=payload.max_rounds,
            use_llm_proposers=payload.use_llm_proposers,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "runtime_failed", "message": str(exc)},
        ) from exc

    # 메시지 피드에 round/proposal trace publish (best-effort, 실패해도 응답 영향 없음).
    from app.services.citylearn_macro_mesh_publish import publish_negotiation_messages
    await publish_negotiation_messages(
        db=db,
        workspace_id=workspace.workspace_id,
        result=result,
        step=payload.step,
        used_llm_proposers=payload.use_llm_proposers,
    )

    return MacroMeshNegotiateResponse(
        run_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
        topology=result.topology,
        initial_violations=result.initial_violations,
        rounds=result.rounds,
        merged_plan=result.merged_plan,
        plan_iteration_trace=result.plan_iteration_trace,
        validation=result.validation,
        operator_summary=result.operator_summary,
        forbidden_action_keys=result.forbidden_action_keys,
    )

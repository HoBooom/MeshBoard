"""CityLearn board runtime endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.models.user import User
from app.services.citylearn_board import get_board_snapshot


router = APIRouter(prefix="/citylearn", tags=["citylearn"])

BaselineModel = Literal["basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"]
AgentMeshMode = Literal["not_configured", "demo_heuristic", "configured_agents"]


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

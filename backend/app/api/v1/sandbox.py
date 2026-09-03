"""Isolated scenario rehearsal API for Agent Mesh creators."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent, AgentSubscriptionRule
from app.models.sandbox import SandboxRun
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceAgent, WorkspaceMember
from app.schemas.sandbox import SandboxEventCreate, SandboxRunRead, SandboxWorkspaceCreate
from app.schemas.workspace import WorkspaceRead
from app.services.sandbox_runtime import simulate_sandbox_event
from app.api.v1.workspaces import (
    CREATOR_ROLES,
    _access_meta,
    _has_any_role,
    _load_agents_for_placements,
    _replace_placements,
    _sync_workspace_nodes,
    _workspace_to_read,
)


router = APIRouter(prefix="/sandbox", tags=["sandbox"])


async def _managed_sandbox(
    db: AsyncSession, workspace_id: UUID, current_user: User
) -> Workspace:
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="샌드박스를 찾을 수 없습니다.")
    if workspace.state != "SANDBOX":
        raise HTTPException(status_code=409, detail="운영 워크스페이스에서는 샌드박스 실행을 할 수 없습니다.")
    access = await _access_meta(db, workspace, current_user)
    if not access["user_can_manage"]:
        raise HTTPException(status_code=403, detail="샌드박스 관리 권한이 없습니다.")
    return workspace


@router.get("/workspaces", response_model=List[WorkspaceRead])
async def list_sandbox_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(Workspace)
            .where(Workspace.state == "SANDBOX")
            .order_by(Workspace.created_at.desc())
        )
    ).scalars().all()
    result = []
    for workspace in rows:
        access = await _access_meta(db, workspace, current_user)
        if access["user_can_access"]:
            result.append(await _workspace_to_read(db, workspace, current_user, meta=access))
    return result


@router.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_sandbox_workspace(
    payload: SandboxWorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _has_any_role(current_user, CREATOR_ROLES):
        raise HTTPException(status_code=403, detail="샌드박스 생성은 개발자 또는 운영자만 가능합니다.")
    await _load_agents_for_placements(db, payload.agent_placements, current_user)
    workspace = Workspace(
        name=payload.name.strip(),
        description=payload.description,
        tags=["sandbox", "isolated"],
        metadata_={"sandbox": True, "isolation": "sandbox_runs"},
        owner_id=current_user.user_id,
        state="SANDBOX",
    )
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.workspace_id,
            user_id=current_user.user_id,
            role="developer",
            granted_by=current_user.user_id,
        )
    )
    await _replace_placements(db, workspace, payload.agent_placements)
    await db.flush()
    await _sync_workspace_nodes(db, workspace)
    await db.flush()
    await db.refresh(workspace)
    return await _workspace_to_read(db, workspace, current_user)


@router.get("/workspaces/{workspace_id}/runs", response_model=List[SandboxRunRead])
async def list_sandbox_runs(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _managed_sandbox(db, workspace_id, current_user)
    runs = (
        await db.execute(
            select(SandboxRun)
            .where(SandboxRun.workspace_id == workspace_id)
            .order_by(SandboxRun.created_at.desc())
        )
    ).scalars().all()
    return [SandboxRunRead.model_validate(run) for run in runs]


@router.post(
    "/workspaces/{workspace_id}/runs",
    response_model=SandboxRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_sandbox_scenario(
    workspace_id: UUID,
    payload: SandboxEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _managed_sandbox(db, workspace_id, current_user)
    agent_ids = (
        await db.execute(
            select(WorkspaceAgent.agent_id).where(
                WorkspaceAgent.workspace_id == workspace_id
            )
        )
    ).scalars().all()
    agents = (
        await db.execute(select(Agent).where(Agent.agent_id.in_(agent_ids)))
    ).scalars().all() if agent_ids else []
    rules = {
        rule.agent_id: rule
        for rule in (
            await db.execute(
                select(AgentSubscriptionRule).where(
                    AgentSubscriptionRule.agent_id.in_(agent_ids)
                )
            )
        ).scalars().all()
    } if agent_ids else {}

    event = payload.model_dump(exclude={"scenario_name"})
    snapshots = []
    for agent in agents:
        rule = rules.get(agent.agent_id)
        snapshots.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "status": agent.status,
                "collaborators": list(agent.collaborators or []),
                "subscription_rule": {
                    "watch_domains": list(rule.watch_domains or []),
                    "watch_intents": list(rule.watch_intents or []),
                    "watch_tags": list(rule.watch_tags or []),
                    "ignore_tags": list(rule.ignore_tags or []),
                    "min_priority": rule.min_priority,
                    "is_active": rule.is_active,
                } if rule else None,
            }
        )
    simulation = simulate_sandbox_event(event, snapshots)
    now = datetime.now(timezone.utc)
    run = SandboxRun(
        workspace_id=workspace_id,
        created_by=current_user.user_id,
        scenario_name=payload.scenario_name.strip(),
        status="COMPLETED",
        event=event,
        decision_log=simulation["decision_log"],
        routed_agent_ids=[UUID(value) for value in simulation["routed_agent_ids"]],
        production_write_count=0,
        completed_at=now,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return SandboxRunRead.model_validate(run)

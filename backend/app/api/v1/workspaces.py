"""
MeshBoard — Workspace API

사용자가 워크스페이스를 생성하고, 해당 워크스페이스에서 사용할 에이전트를 선택합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceAgent
from app.schemas.agent import AgentRead
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdateAgents


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def _load_owned_workspace(
    db: AsyncSession,
    workspace_id: UUID,
    current_user: User,
) -> Workspace:
    result = await db.execute(
        select(Workspace).where(Workspace.workspace_id == workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="워크스페이스를 찾을 수 없습니다.",
        )
    if workspace.owner_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 워크스페이스에 대한 권한이 없습니다.",
        )
    return workspace


async def _load_selectable_agents(
    db: AsyncSession,
    agent_ids: List[UUID],
    current_user: User,
) -> List[Agent]:
    if not agent_ids:
        return []

    unique_ids = list(dict.fromkeys(agent_ids))
    result = await db.execute(select(Agent).where(Agent.agent_id.in_(unique_ids)))
    agents = list(result.scalars().all())
    found_ids = {agent.agent_id for agent in agents}
    missing_ids = [str(agent_id) for agent_id in unique_ids if agent_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"선택한 에이전트를 찾을 수 없습니다: {missing_ids}",
        )

    unauthorized = [
        str(agent.agent_id)
        for agent in agents
        if agent.visibility != "PUBLIC" and agent.owner_id != current_user.user_id
    ]
    if unauthorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"선택할 수 없는 에이전트가 포함되어 있습니다: {unauthorized}",
        )
    return agents


async def _replace_workspace_agents(
    db: AsyncSession,
    workspace: Workspace,
    agents: List[Agent],
) -> None:
    await db.execute(
        delete(WorkspaceAgent).where(WorkspaceAgent.workspace_id == workspace.workspace_id)
    )
    for agent in agents:
        db.add(
            WorkspaceAgent(
                workspace_id=workspace.workspace_id,
                agent_id=agent.agent_id,
            )
        )
    workspace.updated_at = datetime.now(timezone.utc)


async def _workspace_to_read(db: AsyncSession, workspace: Workspace) -> WorkspaceRead:
    result = await db.execute(
        select(Agent)
        .join(WorkspaceAgent, WorkspaceAgent.agent_id == Agent.agent_id)
        .where(WorkspaceAgent.workspace_id == workspace.workspace_id)
        .order_by(Agent.created_at.desc())
    )
    agents = [AgentRead.model_validate(agent) for agent in result.scalars().all()]
    data = WorkspaceRead.model_validate(workspace)
    return data.model_copy(update={"agents": agents})


@router.get("", response_model=List[WorkspaceRead])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 사용자의 워크스페이스 목록을 반환합니다."""
    result = await db.execute(
        select(Workspace)
        .where(Workspace.owner_id == current_user.user_id)
        .order_by(Workspace.created_at.desc())
    )
    responses: List[WorkspaceRead] = []
    for workspace in result.scalars().all():
        responses.append(await _workspace_to_read(db, workspace))
    return responses


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """워크스페이스를 생성하고 사용할 에이전트를 연결합니다."""
    agents = await _load_selectable_agents(db, payload.agent_ids, current_user)
    workspace = Workspace(
        name=payload.name.strip(),
        owner_id=current_user.user_id,
        state="ACTIVE",
    )
    db.add(workspace)
    await db.flush()
    await _replace_workspace_agents(db, workspace, agents)
    await db.flush()
    await db.refresh(workspace)
    return await _workspace_to_read(db, workspace)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """워크스페이스 상세와 선택된 에이전트를 반환합니다."""
    workspace = await _load_owned_workspace(db, workspace_id, current_user)
    return await _workspace_to_read(db, workspace)


@router.put("/{workspace_id}/agents", response_model=WorkspaceRead)
async def update_workspace_agents(
    workspace_id: UUID,
    payload: WorkspaceUpdateAgents,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """워크스페이스에서 사용할 에이전트 목록을 교체합니다."""
    workspace = await _load_owned_workspace(db, workspace_id, current_user)
    agents = await _load_selectable_agents(db, payload.agent_ids, current_user)
    await _replace_workspace_agents(db, workspace, agents)
    await db.flush()
    await db.refresh(workspace)
    return await _workspace_to_read(db, workspace)

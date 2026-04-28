"""MeshBoard — Environment Workspace API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message import Message, MessageHeader, MessageReceipt
from app.models.user import User
from app.models.workspace import (
    Goal,
    Workspace,
    WorkspaceAccessRequest,
    WorkspaceAgent,
    WorkspaceMember,
)
from app.schemas.agent import AgentRead
from app.schemas.workspace import (
    GOAL_PRIORITIES,
    GOAL_STATES,
    GoalCreate,
    GoalRead,
    GoalUpdate,
    WorkspaceAccessRequestCreate,
    WorkspaceAccessRequestRead,
    WorkspaceAgentRead,
    WorkspaceCreate,
    WorkspaceDetailRead,
    WorkspaceMessageRead,
    WorkspaceRead,
    WorkspaceUpdateAgents,
)


router = APIRouter(prefix="/workspaces", tags=["workspaces"])

CREATOR_ROLES = {"agent_owner", "agent_engineer", "trust_ops", "release_manager"}
GRANT_ROLES = {"trust_ops", "release_manager", "evaluator"}


def _has_any_role(user: User, roles: set[str]) -> bool:
    return bool(set(user.roles).intersection(roles))


def _can_create_workspace(user: User) -> bool:
    # governance/admin 역할은 생성 권한 없음. 개발자/운영자 계열만 생성 가능.
    return _has_any_role(user, CREATOR_ROLES)


def _can_grant_access(user: User) -> bool:
    return _has_any_role(user, GRANT_ROLES)


async def _load_workspace(db: AsyncSession, workspace_id: UUID) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.workspace_id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스를 찾을 수 없습니다.")
    return workspace


async def _access_meta(db: AsyncSession, workspace: Workspace, user: User) -> dict:
    if _can_create_workspace(user):
        return {
            "access_status": "system",
            "pending_request_id": None,
            "user_can_access": True,
            "user_can_manage": True,
        }
    if workspace.owner_id == user.user_id:
        return {
            "access_status": "owner",
            "pending_request_id": None,
            "user_can_access": True,
            "user_can_manage": True,
        }
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.workspace_id,
                WorkspaceMember.user_id == user.user_id,
            )
        )
    ).scalar_one_or_none()
    if member:
        return {
            "access_status": "approved",
            "pending_request_id": None,
            "user_can_access": True,
            "user_can_manage": False,
        }
    request = (
        await db.execute(
            select(WorkspaceAccessRequest).where(
                WorkspaceAccessRequest.workspace_id == workspace.workspace_id,
                WorkspaceAccessRequest.requester_id == user.user_id,
                WorkspaceAccessRequest.status == "PENDING",
            )
        )
    ).scalar_one_or_none()
    return {
        "access_status": "pending" if request else "none",
        "pending_request_id": request.request_id if request else None,
        "user_can_access": False,
        "user_can_manage": False,
    }


async def _ensure_access(db: AsyncSession, workspace_id: UUID, user: User) -> Workspace:
    workspace = await _load_workspace(db, workspace_id)
    meta = await _access_meta(db, workspace, user)
    if not meta["user_can_access"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="워크스페이스 접근 권한이 없습니다.")
    return workspace


async def _ensure_manage(db: AsyncSession, workspace_id: UUID, user: User) -> Workspace:
    workspace = await _load_workspace(db, workspace_id)
    meta = await _access_meta(db, workspace, user)
    if not meta["user_can_manage"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="워크스페이스 관리 권한이 없습니다.")
    return workspace


def _progress_for_state(state: str) -> int:
    return {
        "pending": 0,
        "running": 45,
        "blocked": 35,
        "completed": 100,
        "failed": 100,
    }.get(state, 0)


def _ensure_valid_goal_payload(*, priority: Optional[str] = None, state: Optional[str] = None) -> None:
    if priority is not None and priority not in GOAL_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"priority 는 {sorted(GOAL_PRIORITIES)} 중 하나여야 합니다.",
        )
    if state is not None and state not in GOAL_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"state 는 {sorted(GOAL_STATES)} 중 하나여야 합니다.",
        )


async def _load_agents_for_placements(db: AsyncSession, placements, user: User) -> List[Agent]:
    agent_ids = [placement.agent_id for placement in placements]
    if not agent_ids:
        return []
    result = await db.execute(select(Agent).where(Agent.agent_id.in_(agent_ids)))
    agents = list(result.scalars().all())
    found = {agent.agent_id for agent in agents}
    missing = [str(agent_id) for agent_id in agent_ids if agent_id not in found]
    if missing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"에이전트를 찾을 수 없습니다: {missing}")
    unauthorized = [
        str(agent.agent_id)
        for agent in agents
        if agent.visibility != "PUBLIC" and agent.owner_id != user.user_id
    ]
    if unauthorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"선택할 수 없는 에이전트: {unauthorized}")
    return agents


async def _replace_placements(db: AsyncSession, workspace: Workspace, placements) -> None:
    await db.execute(delete(WorkspaceAgent).where(WorkspaceAgent.workspace_id == workspace.workspace_id))
    merged: dict[UUID, int] = {}
    for placement in placements:
        merged[placement.agent_id] = merged.get(placement.agent_id, 0) + placement.quantity
    for agent_id, quantity in merged.items():
        db.add(WorkspaceAgent(workspace_id=workspace.workspace_id, agent_id=agent_id, quantity=quantity))
    workspace.updated_at = datetime.now(timezone.utc)


async def _placement_reads(db: AsyncSession, workspace: Workspace) -> list:
    result = await db.execute(
        select(WorkspaceAgent, Agent)
        .join(Agent, Agent.agent_id == WorkspaceAgent.agent_id)
        .where(WorkspaceAgent.workspace_id == workspace.workspace_id)
        .order_by(Agent.name.asc())
    )
    return [
        WorkspaceAgentRead(agent=AgentRead.model_validate(agent), quantity=placement.quantity)
        for placement, agent in result.all()
    ]


async def _message_reads(
    db: AsyncSession,
    workspace_id: UUID,
    limit: int = 50,
    conversation_id: Optional[UUID] = None,
) -> List[WorkspaceMessageRead]:
    receipt_counts = (
        select(MessageReceipt.message_id, func.count(MessageReceipt.receipt_id).label("receipt_count"))
        .group_by(MessageReceipt.message_id)
        .subquery()
    )
    stmt = (
        select(
            MessageHeader,
            Message.message_id.is_not(None).label("queued"),
            func.coalesce(receipt_counts.c.receipt_count, 0).label("receipt_count"),
        )
        .outerjoin(Message, Message.message_id == MessageHeader.message_id)
        .outerjoin(receipt_counts, receipt_counts.c.message_id == MessageHeader.message_id)
        .where(MessageHeader.workspace_id == workspace_id)
    )
    if conversation_id is not None:
        stmt = stmt.where(MessageHeader.conversation_id == conversation_id)
    result = await db.execute(
        stmt.order_by(MessageHeader.sent_at.desc()).limit(limit)
    )
    rows = list(result.all())
    rows.reverse()
    return [
        WorkspaceMessageRead(
            message_id=header.message_id,
            sender_id=header.sender_id,
            sender_type=header.sender_type,
            sender_name=header.sender_name,
            domain=header.domain,
            intent=header.intent,
            conversation_id=header.conversation_id,
            priority=header.priority,
            tags=header.tags,
            body_ref=header.body_ref,
            sent_at=header.sent_at,
            processed_count=header.processed_count,
            queued=bool(queued),
            receipt_count=int(receipt_count),
        )
        for header, queued, receipt_count in rows
    ]


async def _goal_reads(db: AsyncSession, workspace_id: UUID) -> List[GoalRead]:
    message_counts = (
        select(MessageHeader.conversation_id, func.count(MessageHeader.message_id).label("message_count"))
        .where(MessageHeader.workspace_id == workspace_id)
        .group_by(MessageHeader.conversation_id)
        .subquery()
    )
    result = await db.execute(
        select(Goal, func.coalesce(message_counts.c.message_count, 0).label("message_count"))
        .outerjoin(message_counts, message_counts.c.conversation_id == Goal.conversation_id)
        .where(Goal.workspace_id == workspace_id)
        .order_by(Goal.created_at.asc())
    )
    return [
        GoalRead.model_validate(goal).model_copy(
            update={
                "recent_message_count": int(message_count),
                "progress": _progress_for_state(goal.state),
            }
        )
        for goal, message_count in result.all()
    ]


async def _workspace_to_read(db: AsyncSession, workspace: Workspace, user: User) -> WorkspaceRead:
    meta = await _access_meta(db, workspace, user)
    placements = await _placement_reads(db, workspace) if meta["user_can_access"] else []
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = (
        await db.execute(
            select(func.count(MessageHeader.message_id)).where(
                MessageHeader.workspace_id == workspace.workspace_id,
                MessageHeader.sent_at >= since,
            )
        )
    ).scalar_one()
    data = WorkspaceRead.model_validate(workspace)
    return data.model_copy(
        update={
            **meta,
            "placements": placements,
            "active_agent_count": sum(item.quantity for item in placements),
            "recent_message_count": int(recent_count),
        }
    )


@router.get("", response_model=List[WorkspaceRead])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """접근 가능한 환경과 신청 가능한 전체 환경을 함께 반환합니다."""
    result = await db.execute(select(Workspace).where(Workspace.state == "ACTIVE").order_by(Workspace.created_at.desc()))
    return [await _workspace_to_read(db, workspace, current_user) for workspace in result.scalars().all()]


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """개발자/운영자가 환경 단위 워크스페이스를 생성합니다."""
    if not _can_create_workspace(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="워크스페이스 생성은 개발자 또는 운영자만 가능합니다.")
    await _load_agents_for_placements(db, payload.agent_placements, current_user)
    workspace = Workspace(
        name=payload.name.strip(),
        description=payload.description,
        tags=payload.tags,
        owner_id=current_user.user_id,
        state="ACTIVE",
    )
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.workspace_id,
            user_id=current_user.user_id,
            role="developer" if "agent_engineer" in current_user.roles else "operator",
            granted_by=current_user.user_id,
        )
    )
    await _replace_placements(db, workspace, payload.agent_placements)
    await db.flush()
    await db.refresh(workspace)
    return await _workspace_to_read(db, workspace, current_user)


@router.get("/access-requests", response_model=List[WorkspaceAccessRequestRead])
async def list_access_requests(
    status_value: Optional[str] = "PENDING",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _can_grant_access(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한 신청 조회 권한이 없습니다.")
    stmt = select(WorkspaceAccessRequest).order_by(WorkspaceAccessRequest.created_at.desc())
    if status_value:
        stmt = stmt.where(WorkspaceAccessRequest.status == status_value)
    result = await db.execute(stmt)
    return [WorkspaceAccessRequestRead.model_validate(row) for row in result.scalars().all()]


@router.post("/access-requests/{request_id}/approve", response_model=WorkspaceAccessRequestRead)
async def approve_access_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _can_grant_access(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한 부여는 운영자 또는 평가자만 가능합니다.")
    access_request = (
        await db.execute(select(WorkspaceAccessRequest).where(WorkspaceAccessRequest.request_id == request_id))
    ).scalar_one_or_none()
    if access_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="신청을 찾을 수 없습니다.")
    access_request.status = "APPROVED"
    access_request.decided_by = current_user.user_id
    access_request.decided_at = datetime.now(timezone.utc)
    db.add(
        WorkspaceMember(
            workspace_id=access_request.workspace_id,
            user_id=access_request.requester_id,
            role="viewer",
            granted_by=current_user.user_id,
        )
    )
    await db.flush()
    await db.refresh(access_request)
    return WorkspaceAccessRequestRead.model_validate(access_request)


@router.post("/access-requests/{request_id}/reject", response_model=WorkspaceAccessRequestRead)
async def reject_access_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _can_grant_access(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한 부여는 운영자 또는 평가자만 가능합니다.")
    access_request = (
        await db.execute(select(WorkspaceAccessRequest).where(WorkspaceAccessRequest.request_id == request_id))
    ).scalar_one_or_none()
    if access_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="신청을 찾을 수 없습니다.")
    access_request.status = "REJECTED"
    access_request.decided_by = current_user.user_id
    access_request.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(access_request)
    return WorkspaceAccessRequestRead.model_validate(access_request)


@router.post("/{workspace_id}/access-requests", response_model=WorkspaceAccessRequestRead)
async def request_access(
    workspace_id: UUID,
    payload: WorkspaceAccessRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = await _load_workspace(db, workspace_id)
    meta = await _access_meta(db, workspace, current_user)
    if meta["user_can_access"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 접근 가능한 워크스페이스입니다.")
    pending = (
        await db.execute(
            select(WorkspaceAccessRequest).where(
                WorkspaceAccessRequest.workspace_id == workspace_id,
                WorkspaceAccessRequest.requester_id == current_user.user_id,
                WorkspaceAccessRequest.status == "PENDING",
            )
        )
    ).scalar_one_or_none()
    if pending:
        return WorkspaceAccessRequestRead.model_validate(pending)
    access_request = WorkspaceAccessRequest(
        workspace_id=workspace_id,
        requester_id=current_user.user_id,
        reason=payload.reason,
        status="PENDING",
    )
    db.add(access_request)
    await db.flush()
    await db.refresh(access_request)
    return WorkspaceAccessRequestRead.model_validate(access_request)


@router.get("/{workspace_id}/messages", response_model=List[WorkspaceMessageRead])
async def list_workspace_messages(
    workspace_id: UUID,
    conversation_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_access(db, workspace_id, current_user)
    return await _message_reads(db, workspace_id, conversation_id=conversation_id)


@router.get("/{workspace_id}", response_model=WorkspaceDetailRead)
async def get_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = await _ensure_access(db, workspace_id, current_user)
    data = await _workspace_to_read(db, workspace, current_user)
    messages = await _message_reads(db, workspace_id)
    goals = await _goal_reads(db, workspace_id)
    return WorkspaceDetailRead(**data.model_dump(), messages=messages, goals=goals)


@router.put("/{workspace_id}/agents", response_model=WorkspaceRead)
async def update_workspace_agents(
    workspace_id: UUID,
    payload: WorkspaceUpdateAgents,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = await _ensure_manage(db, workspace_id, current_user)
    await _load_agents_for_placements(db, payload.agent_placements, current_user)
    await _replace_placements(db, workspace, payload.agent_placements)
    await db.flush()
    await db.refresh(workspace)
    return await _workspace_to_read(db, workspace, current_user)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = await _ensure_manage(db, workspace_id, current_user)
    workspace.state = "DELETED"
    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return None


@router.get("/{workspace_id}/goals", response_model=List[GoalRead])
async def list_goals(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_access(db, workspace_id, current_user)
    return await _goal_reads(db, workspace_id)


@router.post("/{workspace_id}/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(
    workspace_id: UUID,
    payload: GoalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = await _ensure_manage(db, workspace_id, current_user)
    _ensure_valid_goal_payload(priority=payload.priority, state=payload.state)
    if payload.parent_goal_id is not None:
        parent = (
            await db.execute(
                select(Goal).where(
                    Goal.goal_id == payload.parent_goal_id,
                    Goal.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="상위 Goal을 찾을 수 없습니다.")

    if payload.assigned_agent_ids:
        existing_agents = (
            await db.execute(
                select(WorkspaceAgent.agent_id).where(
                    WorkspaceAgent.workspace_id == workspace_id,
                    WorkspaceAgent.agent_id.in_(payload.assigned_agent_ids),
                )
            )
        ).scalars().all()
        missing = set(payload.assigned_agent_ids) - set(existing_agents)
        if missing:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="워크스페이스에 배치되지 않은 에이전트가 포함되어 있습니다.")

    goal = Goal(
        workspace_id=workspace_id,
        parent_goal_id=payload.parent_goal_id,
        name=payload.name.strip(),
        description=payload.description,
        priority=payload.priority,
        state=payload.state,
        assigned_agent_ids=payload.assigned_agent_ids,
        success_criteria=payload.success_criteria,
    )
    db.add(goal)
    await db.flush()

    conversation = Conversation(
        workspace_id=workspace.workspace_id,
        goal_id=goal.goal_id,
        initiator_id=current_user.user_id,
        name=goal.name,
        role="goal_thread" if payload.parent_goal_id else "goal_conversation",
        state="ACTIVE",
    )
    db.add(conversation)
    await db.flush()
    goal.conversation_id = conversation.conversation_id
    goal.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(goal)

    return GoalRead.model_validate(goal).model_copy(
        update={"recent_message_count": 0, "progress": _progress_for_state(goal.state)}
    )


@router.put("/{workspace_id}/goals/{goal_id}", response_model=GoalRead)
async def update_goal(
    workspace_id: UUID,
    goal_id: UUID,
    payload: GoalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_manage(db, workspace_id, current_user)
    goal = (
        await db.execute(select(Goal).where(Goal.goal_id == goal_id, Goal.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal을 찾을 수 없습니다.")
    _ensure_valid_goal_payload(priority=payload.priority, state=payload.state)
    if payload.name is not None:
        goal.name = payload.name.strip()
    if payload.description is not None:
        goal.description = payload.description
    if payload.priority is not None:
        goal.priority = payload.priority
    if payload.state is not None:
        goal.state = payload.state
    if payload.assigned_agent_ids is not None:
        goal.assigned_agent_ids = payload.assigned_agent_ids
    if payload.success_criteria is not None:
        goal.success_criteria = payload.success_criteria
    goal.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(goal)
    message_count = (
        await db.execute(
            select(func.count(MessageHeader.message_id)).where(MessageHeader.conversation_id == goal.conversation_id)
        )
    ).scalar_one()
    return GoalRead.model_validate(goal).model_copy(
        update={"recent_message_count": int(message_count), "progress": _progress_for_state(goal.state)}
    )

"""
MeshBoard — Agent-Mesh Messages API

사용자 또는 에이전트가 Agent-Mesh 이벤트 메시지를 발행하는 엔드포인트입니다.
PH3-mesh-001 에서는 MESSAGE_HEADERS 기록까지를 책임집니다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.message import (
    MESSAGE_PRIORITIES,
    MESSAGE_SCOPES,
    MESSAGE_SENDER_TYPES,
    MessageHeaderRead,
    PublishMessageRequest,
    PublishMessageResponse,
    RoutingSummary,
)
from app.services.message_broker import publish_message_header, route_workspace_message


router = APIRouter(prefix="/messages", tags=["messages"])

WORKSPACE_SYSTEM_ROLES = {"agent_owner", "agent_engineer", "trust_ops", "release_manager"}


def _ensure_valid_publish_payload(payload: PublishMessageRequest) -> None:
    if payload.priority not in MESSAGE_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"priority 는 {sorted(MESSAGE_PRIORITIES)} 중 하나여야 합니다.",
        )
    if payload.scope not in MESSAGE_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"scope 는 {sorted(MESSAGE_SCOPES)} 중 하나여야 합니다.",
        )
    if payload.sender_type not in MESSAGE_SENDER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sender_type 은 {sorted(MESSAGE_SENDER_TYPES)} 중 하나여야 합니다.",
        )
    if payload.scope == "workspace" and payload.workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope=workspace 메시지는 workspace_id 가 필요합니다.",
        )


async def _ensure_workspace_access(
    db: AsyncSession,
    workspace_id,
    current_user: User,
) -> None:
    if workspace_id is None:
        return
    result = await db.execute(
        select(Workspace).where(Workspace.workspace_id == workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workspace_id 에 해당하는 워크스페이스를 찾을 수 없습니다.",
        )
    if workspace.owner_id == current_user.user_id or set(current_user.roles).intersection(WORKSPACE_SYSTEM_ROLES):
        return
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == current_user.user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 워크스페이스에 메시지를 발행할 권한이 없습니다.",
        )


async def _ensure_conversation_access(
    db: AsyncSession,
    conversation_id,
    current_user: User,
) -> None:
    if conversation_id is None:
        return
    result = await db.execute(
        select(Conversation).where(Conversation.conversation_id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation_id 에 해당하는 대화를 찾을 수 없습니다.",
        )
    await _ensure_workspace_access(db, conversation.workspace_id, current_user)


async def _resolve_sender(
    db: AsyncSession,
    payload: PublishMessageRequest,
    current_user: User,
):
    if payload.sender_type == "user":
        if payload.sender_id is not None and payload.sender_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="다른 사용자를 발신자로 지정할 수 없습니다.",
            )
        return current_user.user_id, current_user.name

    if payload.sender_type == "agent":
        if payload.sender_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sender_type=agent 메시지는 sender_id 에 agent_id 가 필요합니다.",
            )
        result = await db.execute(select(Agent).where(Agent.agent_id == payload.sender_id))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="sender_id 에 해당하는 에이전트를 찾을 수 없습니다.",
            )
        if agent.owner_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 에이전트를 발신자로 사용할 권한이 없습니다.",
            )
        return agent.agent_id, agent.name

    return current_user.user_id, payload.sender_name or "system"


@router.post("/publish", response_model=PublishMessageResponse, status_code=status.HTTP_201_CREATED)
async def publish_message(
    payload: PublishMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agent-Mesh 메시지를 발행하고 MESSAGE_HEADERS 에 기록합니다."""
    _ensure_valid_publish_payload(payload)
    await _ensure_workspace_access(db, payload.workspace_id, current_user)
    await _ensure_conversation_access(db, payload.conversation_id, current_user)
    sender_id, sender_name = await _resolve_sender(db, payload, current_user)

    header = await publish_message_header(
        db,
        payload,
        sender_id=sender_id,
        sender_name=sender_name,
    )
    routing = await route_workspace_message(db, header)

    return PublishMessageResponse(
        accepted=True,
        message=MessageHeaderRead.model_validate(header),
        routing=RoutingSummary(**routing),
    )

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent import AgentRead


class WorkspaceAgentPlacement(BaseModel):
    """워크스페이스에 배치할 에이전트와 수량."""

    agent_id: UUID
    quantity: int = Field(1, ge=1)


class WorkspaceCreate(BaseModel):
    """환경 단위 워크스페이스 생성 요청."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    agent_placements: List[WorkspaceAgentPlacement] = Field(default_factory=list)


class WorkspaceUpdateAgents(BaseModel):
    """워크스페이스 에이전트 배치 교체 요청."""

    agent_placements: List[WorkspaceAgentPlacement] = Field(default_factory=list)


class WorkspaceAgentRead(BaseModel):
    agent: AgentRead
    quantity: int


class WorkspaceMessageRead(BaseModel):
    message_id: UUID
    sender_id: UUID
    sender_type: str
    sender_name: Optional[str] = None
    domain: Optional[str] = None
    intent: Optional[str] = None
    conversation_id: Optional[UUID] = None
    priority: str
    tags: List[str]
    body_ref: str
    sent_at: datetime
    processed_count: int
    queued: bool
    receipt_count: int


class WorkspaceRead(BaseModel):
    workspace_id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    owner_id: UUID
    state: str
    created_at: datetime
    updated_at: datetime
    placements: List[WorkspaceAgentRead] = Field(default_factory=list)
    active_agent_count: int = 0
    recent_message_count: int = 0
    access_status: str = "none"
    pending_request_id: Optional[UUID] = None
    user_can_access: bool = False
    user_can_manage: bool = False

    model_config = {"from_attributes": True}


GOAL_PRIORITIES = {"low", "medium", "high", "critical"}
GOAL_STATES = {"pending", "running", "blocked", "completed", "failed"}


class GoalCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    priority: str = "medium"
    state: str = "pending"
    parent_goal_id: Optional[UUID] = None
    assigned_agent_ids: List[UUID] = Field(default_factory=list)
    success_criteria: Optional[str] = None


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[str] = None
    state: Optional[str] = None
    assigned_agent_ids: Optional[List[UUID]] = None
    success_criteria: Optional[str] = None


class GoalRead(BaseModel):
    goal_id: UUID
    workspace_id: UUID
    parent_goal_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    priority: str
    state: str
    assigned_agent_ids: List[UUID] = Field(default_factory=list)
    success_criteria: Optional[str] = None
    recent_message_count: int = 0
    progress: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceDetailRead(WorkspaceRead):
    messages: List[WorkspaceMessageRead] = Field(default_factory=list)
    goals: List[GoalRead] = Field(default_factory=list)


class WorkspaceAccessRequestCreate(BaseModel):
    reason: Optional[str] = None


class WorkspaceAccessRequestRead(BaseModel):
    request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    reason: Optional[str] = None
    status: str
    decided_by: Optional[UUID] = None
    decided_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

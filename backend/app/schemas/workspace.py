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


class WorkspaceAgentSubscriptionTarget(BaseModel):
    """워크스페이스 생성 시 agent가 구독할 user/agent 대상."""

    source_agent_id: UUID
    target_node_type: str
    target_ref_id: UUID


class WorkspaceCreate(BaseModel):
    """환경 단위 워크스페이스 생성 요청."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    agent_placements: List[WorkspaceAgentPlacement] = Field(default_factory=list)
    agent_subscriptions: List[WorkspaceAgentSubscriptionTarget] = Field(default_factory=list)


class WorkspaceUpdateAgents(BaseModel):
    """워크스페이스 에이전트 배치 교체 요청."""

    agent_placements: List[WorkspaceAgentPlacement] = Field(default_factory=list)


class WorkspaceAgentToolsUpdate(BaseModel):
    """워크스페이스 관리자가 배치된 에이전트의 사용 도구를 수정하는 요청."""

    tools: List[str] = Field(default_factory=list)


class WorkspaceJoinRequest(BaseModel):
    access_code: str = Field(..., min_length=1, max_length=32)


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


class WorkspaceNodeRead(BaseModel):
    node_id: UUID
    workspace_id: UUID
    node_type: str
    ref_id: UUID
    display_name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceEdgeCreate(BaseModel):
    source_node_id: UUID
    target_node_id: UUID
    edge_type: str = "subscription"


class WorkspaceEdgeRead(BaseModel):
    edge_id: UUID
    workspace_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    edge_type: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    agent_count: int = 0
    user_count: int = 0
    recent_activity_count: int = 0
    active_agent_count: int = 0
    recent_message_count: int = 0
    access_status: str = "none"
    pending_request_id: Optional[UUID] = None
    user_can_access: bool = False
    user_can_manage: bool = False

    model_config = {"from_attributes": True}


class WorkspaceJoinableRead(BaseModel):
    workspace_id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    state: str
    agent_count: int = 0
    user_count: int = 0
    recent_activity_count: int = 0
    access_status: str = "none"
    user_can_access: bool = False


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
    nodes: List[WorkspaceNodeRead] = Field(default_factory=list)
    edges: List[WorkspaceEdgeRead] = Field(default_factory=list)


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

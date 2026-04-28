from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


MESSAGE_PRIORITIES = {"low", "medium", "high", "critical"}
MESSAGE_SCOPES = {"workspace", "department", "global"}
MESSAGE_SENDER_TYPES = {"user", "agent", "system"}


class PublishMessageRequest(BaseModel):
    """Agent-Mesh 메시지 발행 요청."""

    domain: str = Field(..., min_length=1, max_length=100)
    intent: str = Field(..., min_length=1, max_length=100)
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: str = Field("medium", description="low/medium/high/critical")
    tags: List[str] = Field(default_factory=list)
    target_ids: List[UUID] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    scope: str = Field("workspace", description="workspace/department/global")
    workspace_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    execution_tree_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None

    sender_type: str = Field("user", description="user/agent/system")
    sender_id: Optional[UUID] = None
    sender_name: Optional[str] = None


class MessageHeaderRead(BaseModel):
    """MESSAGE_HEADERS 테이블 응답."""

    message_id: UUID
    sender_id: UUID
    sender_type: str
    sender_name: Optional[str] = None
    domain: Optional[str] = None
    intent: Optional[str] = None
    priority: str
    tags: List[str]
    target_ids: List[UUID]
    target_roles: List[str]
    scope: str
    execution_tree_id: Optional[UUID] = None
    workspace_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    body_ref: str
    sent_at: datetime
    expires_at: Optional[datetime] = None
    processed_count: int

    model_config = {"from_attributes": True}


class RoutingSummary(BaseModel):
    queued: bool = False
    queue_message_id: Optional[UUID] = None
    matched_agent_ids: List[UUID] = Field(default_factory=list)
    receipt_ids: List[UUID] = Field(default_factory=list)
    ignored_agent_ids: List[UUID] = Field(default_factory=list)


class PublishMessageResponse(BaseModel):
    """메시지 발행 결과."""

    accepted: bool
    message: MessageHeaderRead
    routing: RoutingSummary = Field(default_factory=RoutingSummary)

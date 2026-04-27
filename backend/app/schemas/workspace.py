from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent import AgentRead


class WorkspaceCreate(BaseModel):
    """워크스페이스 생성 요청."""

    name: str = Field(..., min_length=1, max_length=255)
    agent_ids: List[UUID] = Field(default_factory=list)


class WorkspaceUpdateAgents(BaseModel):
    """워크스페이스에서 사용할 에이전트 목록 교체 요청."""

    agent_ids: List[UUID] = Field(default_factory=list)


class WorkspaceRead(BaseModel):
    """워크스페이스 응답."""

    workspace_id: UUID
    name: Optional[str] = None
    owner_id: UUID
    state: str
    created_at: datetime
    updated_at: datetime
    agents: List[AgentRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}

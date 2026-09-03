from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.workspace import WorkspaceAgentPlacement


class SandboxWorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    agent_placements: List[WorkspaceAgentPlacement] = Field(default_factory=list)


class SandboxEventCreate(BaseModel):
    scenario_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    intent: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=4000)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    tags: List[str] = Field(default_factory=list)


class SandboxDecisionRead(BaseModel):
    sequence: int
    agent_id: UUID
    agent_name: str
    action: str
    reason: str
    status: str


class SandboxIsolationRead(BaseModel):
    mode: str = "sandbox_only"
    message_headers_written: int = 0
    messages_written: int = 0
    interactions_written: int = 0


class SandboxRunRead(BaseModel):
    run_id: UUID
    workspace_id: UUID
    created_by: UUID
    scenario_name: str
    status: str
    event: Dict[str, Any]
    decision_log: List[SandboxDecisionRead]
    routed_agent_ids: List[UUID]
    production_write_count: int
    isolation: SandboxIsolationRead = Field(default_factory=SandboxIsolationRead)
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

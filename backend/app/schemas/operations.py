"""MeshBoard — 운영 관리(Operations Console) 스키마."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ── Overview ──────────────────────────────────────────────────────
class AgentStatusBreakdown(BaseModel):
    ACTIVE: int = 0
    DRAFT: int = 0
    DEPRECATED: int = 0
    SUSPENDED: int = 0


class OperationsOverview(BaseModel):
    total_agents: int
    status_breakdown: AgentStatusBreakdown
    visibility_breakdown: Dict[str, int] = Field(default_factory=dict)
    total_interactions: int
    interactions_24h: int
    failed_interactions: int
    success_rate: float  # 0~100 (%)
    total_tokens: int


# ── Agent Lifecycle ───────────────────────────────────────────────
class AgentOpsRead(BaseModel):
    agent_id: uuid.UUID
    name: str
    version: str
    status: str
    visibility: str
    owner_name: Optional[str] = None
    tool_count: int = 0
    updated_at: datetime
    last_activity: Optional[datetime] = None


class AgentStatusUpdate(BaseModel):
    status: str = Field(..., max_length=20)


# ── Activity Log ──────────────────────────────────────────────────
class ActivityRead(BaseModel):
    interaction_id: uuid.UUID
    actor_name: str
    target_name: Optional[str] = None
    kind: str
    state: str
    start_timestamp: datetime
    duration_ms: Optional[int] = None
    model_used: Optional[str] = None
    error_message: Optional[str] = None


# ── System Health ─────────────────────────────────────────────────
class HealthComponent(BaseModel):
    name: str
    status: str  # "online" | "degraded" | "offline"
    detail: str


class SystemHealth(BaseModel):
    components: List[HealthComponent]

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
    active_executions: int = 0
    control_generation: int = 0


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


class ExecutionSummaryRead(BaseModel):
    execution_tree_id: uuid.UUID
    root_interaction_id: uuid.UUID
    conversation_id: uuid.UUID
    actor_name: str
    prompt: Optional[str] = None
    state: str
    node_count: int
    duration_ms: Optional[int] = None
    started_at: datetime


class ExecutionNodeRead(BaseModel):
    interaction_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = None
    execution_tree_id: uuid.UUID
    tree_depth: int
    tree_path: str
    actor_name: str
    target_name: Optional[str] = None
    kind: str
    state: str
    duration_ms: Optional[int] = None
    reasoning_trace: Optional[str] = None
    results: Optional[str] = None
    tool_name: Optional[str] = None
    error_message: Optional[str] = None
    start_timestamp: datetime
    payload: Dict[str, object] = Field(default_factory=dict)


class ExecutionTreeRead(BaseModel):
    execution_tree_id: uuid.UUID
    nodes: List[ExecutionNodeRead] = Field(default_factory=list)


class ArchiveResultRead(BaseModel):
    retention_days: int
    cutoff: datetime
    eligible_count: int
    archived_count: int
    dry_run: bool


class ModelAnalyticsRead(BaseModel):
    model: str
    execution_count: int
    failed_count: int
    token_input: int
    token_output: int
    total_tokens: int
    average_duration_ms: float
    estimated_cost_usd: Optional[float] = None


class ParallelGroupAnalyticsRead(BaseModel):
    parallel_group_id: uuid.UUID
    execution_count: int
    wall_duration_ms: int
    serial_duration_ms: int
    saved_duration_ms: int


class OperationsAnalyticsRead(BaseModel):
    models: List[ModelAnalyticsRead] = Field(default_factory=list)
    parallel_groups: List[ParallelGroupAnalyticsRead] = Field(default_factory=list)


class ConnectorStatusRead(BaseModel):
    configured: bool
    endpoint: Optional[str] = None
    production_https_required: bool = True


class ConnectorTestRead(BaseModel):
    configured: bool
    delivered: bool
    status_code: Optional[int] = None
    error: Optional[str] = None


# ── System Health ─────────────────────────────────────────────────
class HealthComponent(BaseModel):
    name: str
    status: str  # "online" | "degraded" | "offline"
    detail: str


class SystemHealth(BaseModel):
    components: List[HealthComponent]

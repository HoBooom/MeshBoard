from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','SANDBOX','ARCHIVED','DELETED')", name="ck_ws_state"),
    )

class Goal(Base):
    __tablename__ = "goals"

    goal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    parent_goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("goals.goal_id", ondelete="CASCADE"))
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    assigned_agent_ids: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    success_criteria: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("priority IN ('low','medium','high','critical')", name="ck_goals_priority"),
        CheckConstraint("state IN ('pending','running','blocked','completed','failed')", name="ck_goals_state"),
    )


class WorkspaceAgent(Base):
    __tablename__ = "workspace_agents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        primary_key=True,
    )
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_workspace_agents_quantity"),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"))
    granted_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("role IN ('viewer','operator','developer')", name="ck_workspace_members_role"),
    )


class WorkspaceNode(Base):
    __tablename__ = "workspace_nodes"

    node_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_type: Mapped[str] = mapped_column(String(10), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("node_type IN ('user','agent')", name="ck_workspace_nodes_node_type"),
        CheckConstraint("status IN ('active','idle','processing','error')", name="ck_workspace_nodes_status"),
        UniqueConstraint("workspace_id", "node_type", "ref_id", name="uq_workspace_nodes_ref"),
    )


class WorkspaceEdge(Base):
    __tablename__ = "workspace_edges"

    edge_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspace_nodes.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspace_nodes.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(String(30), nullable=False, default="subscription")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("edge_type IN ('subscription')", name="ck_workspace_edges_edge_type"),
        CheckConstraint("status IN ('active','disabled')", name="ck_workspace_edges_status"),
        UniqueConstraint(
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_workspace_edges_subscription",
        ),
    )


class WorkspaceAccessRequest(Base):
    __tablename__ = "workspace_access_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_workspace_access_requests_status"),
    )

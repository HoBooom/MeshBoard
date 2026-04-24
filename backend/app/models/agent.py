from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    approach: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="PRIVATE")
    
    agent_card: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    roles: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    collaborators: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    tools: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','DEPRECATED','SUSPENDED')", name="ck_agents_status"),
        CheckConstraint("visibility IN ('PUBLIC','DEPARTMENT','PRIVATE')", name="ck_agents_visibility"),
    )

class AgentSubscriptionRule(Base):
    __tablename__ = "agent_subscription_rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.agent_id", ondelete="CASCADE"), nullable=False)
    
    watch_domains: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    watch_intents: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    watch_tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    watch_senders: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    watch_roles: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    
    ignore_senders: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    ignore_tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    
    min_priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("min_priority IN ('low','medium','high','critical')", name="ck_asr_priority"),
    )

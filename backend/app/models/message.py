from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("goals.goal_id"))
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversations.conversation_id"))
    interaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True)) # Logical FK to interactions
    
    participant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    participant_type: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("participant_type IN ('user','agent','system')", name="ck_msg_participant_type"),
    )

class MessageHeader(Base):
    __tablename__ = "message_headers"

    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    intent: Mapped[Optional[str]] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    
    target_ids: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    target_roles: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    
    execution_tree_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"))
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversations.conversation_id"))
    
    body_ref: Mapped[str] = mapped_column(Text, nullable=False)
    
    sent_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("sender_type IN ('user','agent','system')", name="ck_mh_sender_type"),
        CheckConstraint("priority IN ('low','medium','high','critical')", name="ck_mh_priority"),
        CheckConstraint("scope IN ('workspace','department','global')", name="ck_mh_scope"),
    )

class MessageReceipt(Base):
    __tablename__ = "message_receipts"

    receipt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False) # Logical FK to message_headers
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.agent_id"), nullable=False)
    
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    reason: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("decision IN ('consumed','ignored','expired','failed')", name="ck_mr_decision"),
    )

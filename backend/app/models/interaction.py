from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_utils import LtreeType

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Interaction(Base):
    __tablename__ = "interactions"

    interaction_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 워크스페이스 대화 밖에서 일어나는 실행(에이전트 직접 호출)도 기록하므로 비어 있을 수 있다.
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=True)
    schema_ver: Mapped[str] = mapped_column(String(10), nullable=False, default="1.0")
    
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interactions.interaction_id"))
    execution_tree_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    tree_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tree_path: Mapped[Optional[str]] = mapped_column(LtreeType)
    parallel_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    delegation_type: Mapped[Optional[str]] = mapped_column(String(20))
    
    start_timestamp: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    complete_timestamp: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    target_type: Mapped[Optional[str]] = mapped_column(String(10))
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    target_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="message")
    step_id: Mapped[Optional[int]] = mapped_column(Integer)
    prompt: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    results: Mapped[Optional[str]] = mapped_column(Text)
    reasoning_trace: Mapped[Optional[str]] = mapped_column(Text)
    tool_name: Mapped[Optional[str]] = mapped_column(String(255))
    tool_input: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    tool_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    
    involved_agents: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    token_input: Mapped[Optional[int]] = mapped_column(Integer)
    token_output: Mapped[Optional[int]] = mapped_column(Integer)
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("delegation_type IN ('user_request','orchestration','peer','pipeline','parallel')", name="ck_inter_delegation"),
        CheckConstraint("actor_type IN ('user','agent','system')", name="ck_inter_actor_type"),
        CheckConstraint("target_type IN ('user','agent','broadcast')", name="ck_inter_target_type"),
        CheckConstraint("kind IN ('message','tool_call','tool_result','reasoning','handoff','error')", name="ck_inter_kind"),
        CheckConstraint("state IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')", name="ck_inter_state"),
    )

class InteractionArchive(Base):
    __tablename__ = "interaction_archive"

    # Copy of interactions fields
    interaction_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    schema_ver: Mapped[str] = mapped_column(String(10), nullable=False, default="1.0")
    
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    execution_tree_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    tree_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tree_path: Mapped[Optional[str]] = mapped_column(LtreeType)
    parallel_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    delegation_type: Mapped[Optional[str]] = mapped_column(String(20))
    
    start_timestamp: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    complete_timestamp: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    target_type: Mapped[Optional[str]] = mapped_column(String(10))
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    target_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    step_id: Mapped[Optional[int]] = mapped_column(Integer)
    prompt: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    results: Mapped[Optional[str]] = mapped_column(Text)
    reasoning_trace: Mapped[Optional[str]] = mapped_column(Text)
    tool_name: Mapped[Optional[str]] = mapped_column(String(255))
    tool_input: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    tool_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    
    involved_agents: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    token_input: Mapped[Optional[int]] = mapped_column(Integer)
    token_output: Mapped[Optional[int]] = mapped_column(Integer)
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    
    # Archive specific fields
    archived_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    is_immutable: Mapped[bool] = mapped_column(nullable=False, default=True)

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    owner_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','ARCHIVED','DELETED')", name="ck_ws_state"),
    )

class Goal(Base):
    __tablename__ = "goals"

    goal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','COMPLETED','CANCELLED')", name="ck_goals_state"),
    )

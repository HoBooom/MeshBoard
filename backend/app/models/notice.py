from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Notice(Base):
    __tablename__ = "notices"

    notice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    target_role: Mapped[str] = mapped_column(String(50), nullable=False, default="all")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"))
    
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint("target_role IN ('all','agent_owner','agent_engineer','trust_ops','governance','evaluator','ethics_liaison','release_manager')", name="ck_notices_role"),
    )

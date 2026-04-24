from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIMESTAMPTZ = DateTime(timezone=True)

class Certification(Base):
    __tablename__ = "certifications"

    certification_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    certifier_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id"))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    issued_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("state IN ('PENDING','PASSED','FAILED','REVOKED')", name="ck_certs_state"),
    )

class AgentCertification(Base):
    __tablename__ = "agent_certifications"

    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True)
    certification_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("certifications.certification_id", ondelete="CASCADE"), primary_key=True)
    
    linked_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc))

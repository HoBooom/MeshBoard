from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


TIMESTAMPTZ = DateTime(timezone=True)


class SandboxRun(Base):
    """A deterministic Agent Mesh rehearsal isolated from operational messages.

    Sandbox runs intentionally persist only their input and decision trace. They
    never create MessageHeader, Message, MessageReceipt, or Interaction rows.
    """

    __tablename__ = "sandbox_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    scenario_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    event: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    decision_log: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    routed_agent_ids: Mapped[List[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list
    )
    production_write_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint(
            "status IN ('COMPLETED','FAILED')", name="ck_sandbox_runs_status"
        ),
        CheckConstraint(
            "production_write_count = 0", name="ck_sandbox_runs_no_production_writes"
        ),
    )

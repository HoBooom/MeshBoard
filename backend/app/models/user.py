"""
MeshBoard — User & UserRole ORM Models

schema_v1.sql의 users, user_roles 테이블 매핑.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

TIMESTAMPTZ = DateTime(timezone=True)

from app.db.base import Base


class User(Base):
    """시스템 사용자 테이블."""

    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    login_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # OIDC 연동 필드
    idp_sub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    idp_iss: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Relationships
    role_entries: Mapped[List["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        foreign_keys="[UserRole.user_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("idp_sub", "idp_iss", name="uq_users_idp"),
        CheckConstraint(
            "state IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')",
            name="ck_users_state",
        ),
    )

    @property
    def roles(self) -> list[str]:
        """사용자의 역할 목록을 반환합니다."""
        return [r.role for r in self.role_entries]

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.state})>"


class UserRole(Base):
    """사용자 역할 매핑 테이블 — 한 사용자가 여러 역할 보유 가능."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="role_entries", foreign_keys="[UserRole.user_id]")

    __table_args__ = (
        CheckConstraint(
            "role IN ('agent_owner', 'agent_engineer', 'trust_ops', "
            "'governance', 'evaluator', 'ethics_liaison', 'release_manager')",
            name="ck_user_roles_role",
        ),
    )

    def __repr__(self) -> str:
        return f"<UserRole {self.user_id}:{self.role}>"

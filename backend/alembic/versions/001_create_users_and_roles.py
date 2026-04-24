"""Create users and user_roles tables

Revision ID: 001_users_roles
Revises:
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "001_users_roles"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto 확장 (gen_random_uuid 용)
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # users 테이블
    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("login_id", sa.String(50), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("idp_sub", sa.String(255), nullable=True),
        sa.Column("idp_iss", sa.String(255), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idp_sub", "idp_iss", name="uq_users_idp"),
        sa.CheckConstraint("state IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')", name="ck_users_state"),
    )

    # users 인덱스
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_idp", "users", ["idp_sub", "idp_iss"], postgresql_where=sa.text("idp_sub IS NOT NULL"))
    op.create_index("idx_users_state", "users", ["state"], postgresql_where=sa.text("state = 'ACTIVE'"))

    # user_roles 테이블
    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(50), primary_key=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("granted_by", UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=True),
        sa.CheckConstraint(
            "role IN ('agent_owner', 'agent_engineer', 'trust_ops', "
            "'governance', 'evaluator', 'ethics_liaison', 'release_manager')",
            name="ck_user_roles_role",
        ),
    )

    # user_roles 인덱스
    op.create_index("idx_user_roles_role", "user_roles", ["role"])


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("users")

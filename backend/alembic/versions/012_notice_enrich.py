"""notice category/priority/pinned

Revision ID: 012_notice_enrich
Revises: 011_workspace_metadata
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "012_notice_enrich"
down_revision = "011_workspace_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("category", sa.String(length=20), nullable=False, server_default="general"),
    )
    op.add_column(
        "notices",
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="normal"),
    )
    op.add_column(
        "notices",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_check_constraint(
        "ck_notices_category",
        "notices",
        "category IN ('general','system','city','governance','release','security')",
    )
    op.create_check_constraint(
        "ck_notices_priority",
        "notices",
        "priority IN ('normal','high','critical')",
    )

    op.alter_column("notices", "category", server_default=None)
    op.alter_column("notices", "priority", server_default=None)
    op.alter_column("notices", "pinned", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_notices_priority", "notices", type_="check")
    op.drop_constraint("ck_notices_category", "notices", type_="check")
    op.drop_column("notices", "pinned")
    op.drop_column("notices", "priority")
    op.drop_column("notices", "category")

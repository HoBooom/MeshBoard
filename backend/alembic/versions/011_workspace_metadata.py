"""workspace metadata json

Revision ID: 011_workspace_metadata
Revises: 010_workspace_edges
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "011_workspace_metadata"
down_revision = "010_workspace_edges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("workspaces", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("workspaces", "metadata")

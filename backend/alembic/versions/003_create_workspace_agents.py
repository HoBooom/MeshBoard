"""create workspace agents association

Revision ID: 003_create_workspace_agents
Revises: bd44babbb822
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "003_create_workspace_agents"
down_revision = "bd44babbb822"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_agents",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "agent_id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_agents")

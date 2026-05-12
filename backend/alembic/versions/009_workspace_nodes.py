"""workspace node graph model

Revision ID: 009_workspace_nodes
Revises: 008_workspace_graph
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "009_workspace_nodes"
down_revision = "008_workspace_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_nodes",
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("node_type", sa.String(length=10), nullable=False),
        sa.Column("ref_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("node_type IN ('user','agent')", name="ck_workspace_nodes_node_type"),
        sa.CheckConstraint("status IN ('active','idle','processing','error')", name="ck_workspace_nodes_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("node_id"),
        sa.UniqueConstraint("workspace_id", "node_type", "ref_id", name="uq_workspace_nodes_ref"),
    )
    op.create_index("ix_workspace_nodes_workspace", "workspace_nodes", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_nodes_workspace", table_name="workspace_nodes")
    op.drop_table("workspace_nodes")

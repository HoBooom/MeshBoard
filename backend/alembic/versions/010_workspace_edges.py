"""workspace edge graph model

Revision ID: 010_workspace_edges
Revises: 009_workspace_nodes
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "010_workspace_edges"
down_revision = "009_workspace_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_edges",
        sa.Column("edge_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("edge_type", sa.String(length=30), nullable=False, server_default="subscription"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("edge_type IN ('subscription')", name="ck_workspace_edges_edge_type"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_workspace_edges_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_node_id"], ["workspace_nodes.node_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["workspace_nodes.node_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("edge_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_workspace_edges_subscription",
        ),
    )
    op.create_index("ix_workspace_edges_workspace", "workspace_edges", ["workspace_id"])
    op.create_index("ix_workspace_edges_target", "workspace_edges", ["workspace_id", "target_node_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_edges_target", table_name="workspace_edges")
    op.drop_index("ix_workspace_edges_workspace", table_name="workspace_edges")
    op.drop_table("workspace_edges")

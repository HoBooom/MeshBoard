"""workspace subscription graph

Revision ID: 008_workspace_graph
Revises: 007_goal_orchestration
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "008_workspace_graph"
down_revision = "007_goal_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_subscription_edges",
        sa.Column("edge_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("source_node_type", sa.String(length=10), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_type", sa.String(length=10), nullable=False),
        sa.Column("edge_type", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_node_type IN ('user','agent')", name="ck_workspace_subscription_source_type"),
        sa.CheckConstraint("target_node_type IN ('user','agent')", name="ck_workspace_subscription_target_type"),
        sa.CheckConstraint("edge_type IN ('subscription')", name="ck_workspace_subscription_edge_type"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("edge_id"),
    )
    op.create_index(
        "ix_workspace_subscription_edges_workspace",
        "workspace_subscription_edges",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_subscription_edges_workspace", table_name="workspace_subscription_edges")
    op.drop_table("workspace_subscription_edges")

"""goal orchestration fields

Revision ID: 007_goal_orchestration
Revises: 006_workspace_member_creator
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_goal_orchestration"
down_revision = "006_workspace_member_creator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_goals_state", "goals", type_="check")
    op.add_column("goals", sa.Column("parent_goal_id", sa.UUID(), nullable=True))
    op.add_column("goals", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column("goals", sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"))
    op.add_column(
        "goals",
        sa.Column("assigned_agent_ids", postgresql.ARRAY(sa.UUID()), nullable=False, server_default="{}"),
    )
    op.add_column("goals", sa.Column("success_criteria", sa.Text(), nullable=True))
    op.alter_column("goals", "state", server_default="pending")
    op.execute("UPDATE goals SET state = CASE WHEN state = 'ACTIVE' THEN 'running' WHEN state = 'COMPLETED' THEN 'completed' WHEN state = 'CANCELLED' THEN 'failed' ELSE lower(state) END")
    op.create_foreign_key(
        "fk_goals_parent_goal_id",
        "goals",
        "goals",
        ["parent_goal_id"],
        ["goal_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("ck_goals_priority", "goals", "priority IN ('low','medium','high','critical')")
    op.create_check_constraint("ck_goals_state", "goals", "state IN ('pending','running','blocked','completed','failed')")
    op.alter_column("goals", "priority", server_default=None)
    op.alter_column("goals", "assigned_agent_ids", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_goals_state", "goals", type_="check")
    op.drop_constraint("ck_goals_priority", "goals", type_="check")
    op.drop_constraint("fk_goals_parent_goal_id", "goals", type_="foreignkey")
    op.execute("UPDATE goals SET state = CASE WHEN state = 'running' THEN 'ACTIVE' WHEN state = 'completed' THEN 'COMPLETED' ELSE 'CANCELLED' END")
    op.create_check_constraint("ck_goals_state", "goals", "state IN ('ACTIVE','COMPLETED','CANCELLED')")
    op.drop_column("goals", "success_criteria")
    op.drop_column("goals", "assigned_agent_ids")
    op.drop_column("goals", "priority")
    op.drop_column("goals", "conversation_id")
    op.drop_column("goals", "parent_goal_id")

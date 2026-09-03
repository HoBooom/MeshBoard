"""Add isolated sandbox workspaces and run records.

Revision ID: 013_sandbox_runs
Revises: 012_notice_enrich
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "013_sandbox_runs"
down_revision = "012_notice_enrich"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ws_state", "workspaces", type_="check")
    op.create_check_constraint(
        "ck_ws_state",
        "workspaces",
        "state IN ('ACTIVE','SANDBOX','ARCHIVED','DELETED')",
    )
    op.create_table(
        "sandbox_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("scenario_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("event", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "routed_agent_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("production_write_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('COMPLETED','FAILED')", name="ck_sandbox_runs_status"
        ),
        sa.CheckConstraint(
            "production_write_count = 0", name="ck_sandbox_runs_no_production_writes"
        ),
    )
    op.create_index(
        "ix_sandbox_runs_workspace_id", "sandbox_runs", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_sandbox_runs_workspace_id", table_name="sandbox_runs")
    op.drop_table("sandbox_runs")
    op.drop_constraint("ck_ws_state", "workspaces", type_="check")
    op.create_check_constraint(
        "ck_ws_state",
        "workspaces",
        "state IN ('ACTIVE','ARCHIVED','DELETED')",
    )

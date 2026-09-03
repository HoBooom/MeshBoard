"""Normalize the legacy workspace member creator role.

Revision ID: 015_member_role
Revises: 014_archive_immutability
"""

from alembic import op


revision = "015_member_role"
down_revision = "014_archive_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Early demo databases used ``creator`` while the application model and
    # access checks have always used ``developer``. Preserve memberships and
    # converge the persisted schema on the application vocabulary.
    op.drop_constraint("ck_workspace_members_role", "workspace_members", type_="check")
    op.execute("UPDATE workspace_members SET role = 'developer' WHERE role = 'creator'")
    op.create_check_constraint(
        "ck_workspace_members_role",
        "workspace_members",
        "role IN ('viewer','operator','developer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_members_role", "workspace_members", type_="check")
    op.execute("UPDATE workspace_members SET role = 'creator' WHERE role = 'developer'")
    op.create_check_constraint(
        "ck_workspace_members_role",
        "workspace_members",
        "role IN ('viewer','operator','creator')",
    )

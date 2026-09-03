"""Protect the interaction archive from mutation.

Revision ID: 014_archive_immutability
Revises: 013_sandbox_runs
"""

from alembic import op


revision = "014_archive_immutability"
down_revision = "013_sandbox_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_interaction_archive_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'interaction_archive rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER interaction_archive_immutable
        BEFORE UPDATE OR DELETE ON interaction_archive
        FOR EACH ROW EXECUTE FUNCTION prevent_interaction_archive_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS interaction_archive_immutable ON interaction_archive")
    op.execute("DROP FUNCTION IF EXISTS prevent_interaction_archive_mutation()")

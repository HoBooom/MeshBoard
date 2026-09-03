"""Allow interactions that do not belong to a workspace conversation.

Revision ID: 016_standalone_interactions
Revises: 015_member_role
"""

import sqlalchemy as sa
from alembic import op


revision = "016_standalone_interactions"
down_revision = "015_member_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 직접 호출(`POST /agents/{id}/invoke`)은 워크스페이스 대화 밖에서 일어나는 실행이다.
    # conversations 는 workspace_id 를 요구하므로, 대화를 억지로 만들지 않고
    # conversation_id 를 비워 둔 채 실행 트리를 남길 수 있게 한다.
    op.alter_column(
        "interactions",
        "conversation_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "interaction_archive",
        "conversation_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # 워크스페이스에 속하지 않는 실행 기록은 되돌릴 때 표현할 수 없으므로 제거한다.
    op.execute("DELETE FROM interaction_archive WHERE conversation_id IS NULL")
    op.execute("DELETE FROM interactions WHERE conversation_id IS NULL")
    op.alter_column(
        "interaction_archive",
        "conversation_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "interactions",
        "conversation_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

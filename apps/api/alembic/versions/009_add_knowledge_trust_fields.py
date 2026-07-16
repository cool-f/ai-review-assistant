"""add editable knowledge indexing state and chat citations

Revision ID: 009
Revises: 008
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("knowledge_points", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("knowledge_points", sa.Column("indexing_status", sa.String(32), nullable=False, server_default="completed"))
    op.add_column("knowledge_points", sa.Column("indexing_error", sa.Text(), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column("citations", postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "citations")
    op.drop_column("knowledge_points", "indexing_error")
    op.drop_column("knowledge_points", "indexing_status")
    op.drop_column("knowledge_points", "revision")

"""add course boundary and explicit courseware processing stages

Revision ID: 007
Revises: 006
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_COURSE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("term", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO courses (id, name, term, description) "
            "SELECT CAST(:id AS uuid), '默认课程', '', '由历史数据迁移自动创建' "
            "WHERE EXISTS ("
            "SELECT 1 FROM coursewares UNION ALL "
            "SELECT 1 FROM homeworks UNION ALL "
            "SELECT 1 FROM folders UNION ALL "
            "SELECT 1 FROM chat_sessions"
            ")"
        ).bindparams(id=DEFAULT_COURSE_ID)
    )

    for table in ("coursewares", "homeworks", "folders", "chat_sessions"):
        op.add_column(
            table,
            sa.Column("course_id", postgresql.UUID(as_uuid=False), nullable=True),
        )
        op.execute(
            sa.text(f"UPDATE {table} SET course_id = CAST(:id AS uuid) WHERE course_id IS NULL")
            .bindparams(id=DEFAULT_COURSE_ID)
        )
        op.alter_column(table, "course_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_course_id", table, "courses", ["course_id"], ["id"], ondelete="CASCADE"
        )

    op.create_index("ix_folders_course_id", "folders", ["course_id"])
    op.create_index("ix_chat_sessions_course_id", "chat_sessions", ["course_id"])

    for column in ("parse_status", "knowledge_status", "embedding_status", "linking_status"):
        op.add_column(
            "coursewares",
            sa.Column(column, sa.String(32), nullable=False, server_default="pending"),
        )
    op.add_column("coursewares", sa.Column("failed_stage", sa.String(32), nullable=True))
    op.add_column(
        "coursewares", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute(
        """
        UPDATE coursewares
        SET parse_status = CASE WHEN original_text IS NOT NULL AND length(original_text) > 0 THEN 'completed' ELSE status END,
            knowledge_status = CASE WHEN status = 'completed' THEN 'completed' ELSE status END,
            embedding_status = CASE WHEN status = 'completed' THEN 'completed' ELSE 'pending' END,
            linking_status = CASE WHEN status = 'completed' THEN 'completed' ELSE 'pending' END,
            failed_stage = CASE WHEN status = 'failed' THEN 'parse' ELSE NULL END
        """
    )


def downgrade() -> None:
    for column in ("retry_count", "failed_stage", "linking_status", "embedding_status", "knowledge_status", "parse_status"):
        op.drop_column("coursewares", column)
    op.drop_index("ix_chat_sessions_course_id", table_name="chat_sessions")
    op.drop_index("ix_folders_course_id", table_name="folders")
    for table in ("chat_sessions", "folders", "homeworks", "coursewares"):
        op.drop_constraint(f"fk_{table}_course_id", table, type_="foreignkey")
        op.drop_column(table, "course_id")
    op.drop_table("courses")

"""add usage dimensions and idempotent chat requests

Revision ID: 010
Revises: 009
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The legacy ORM declared this table, but migrations 001-009 never created
    # it.  Fresh/standard databases therefore need the complete table here.
    # Keep the online fallback for databases that created it out-of-band.
    usage_table_exists = not context.is_offline_mode() and sa.inspect(
        op.get_bind()
    ).has_table("token_usage_logs")
    if usage_table_exists:
        op.add_column(
            "token_usage_logs",
            sa.Column(
                "purpose",
                sa.String(64),
                nullable=False,
                server_default="unspecified",
            ),
        )
        op.add_column(
            "token_usage_logs",
            sa.Column(
                "course_id", postgresql.UUID(as_uuid=False), nullable=True
            ),
        )
        op.add_column(
            "token_usage_logs",
            sa.Column(
                "estimated_cost_usd",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
        )
        op.create_foreign_key(
            "fk_token_usage_logs_course_id",
            "token_usage_logs",
            "courses",
            ["course_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_token_usage_logs_purpose", "token_usage_logs", ["purpose"]
        )
        op.create_index(
            "ix_token_usage_logs_course_id", "token_usage_logs", ["course_id"]
        )
    else:
        op.create_table(
            "token_usage_logs",
            sa.Column(
                "id", postgresql.UUID(as_uuid=False), nullable=False
            ),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column(
                "purpose",
                sa.String(64),
                nullable=False,
                server_default="unspecified",
            ),
            sa.Column(
                "prompt_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "completion_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "session_id", postgresql.UUID(as_uuid=False), nullable=True
            ),
            sa.Column(
                "course_id", postgresql.UUID(as_uuid=False), nullable=True
            ),
            sa.Column(
                "estimated_cost_usd",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "prompt_tokens >= 0", name="ck_tul_prompt_tokens_non_negative"
            ),
            sa.CheckConstraint(
                "completion_tokens >= 0",
                name="ck_tul_completion_tokens_non_negative",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["chat_sessions.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["course_id"],
                ["courses.id"],
                name="fk_token_usage_logs_course_id",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_token_usage_logs_created_at", "token_usage_logs", ["created_at"]
        )
        op.create_index(
            "ix_token_usage_logs_provider", "token_usage_logs", ["provider"]
        )
        op.create_index(
            "ix_token_usage_logs_session_id", "token_usage_logs", ["session_id"]
        )
        op.create_index(
            "ix_token_usage_logs_purpose", "token_usage_logs", ["purpose"]
        )
        op.create_index(
            "ix_token_usage_logs_course_id", "token_usage_logs", ["course_id"]
        )

    op.create_table(
        "chat_requests",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="processing"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_chat_requests_idempotency_key"),
    )
    op.create_index("ix_chat_requests_session_id", "chat_requests", ["session_id"])
    op.create_index("ix_chat_requests_status", "chat_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_chat_requests_status", table_name="chat_requests")
    op.drop_index("ix_chat_requests_session_id", table_name="chat_requests")
    op.drop_table("chat_requests")
    op.drop_table("token_usage_logs")

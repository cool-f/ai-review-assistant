"""add practice attempts and consecutive-correct progress

Revision ID: 008
Revises: 007
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "study_progress",
        sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "practice_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("submitted_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("grading_method", sa.String(32), nullable=False),
        sa.Column("counted_for_progress", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["question_id"], ["generated_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_attempts_question_id", "practice_attempts", ["question_id"])
    op.create_index("ix_practice_attempts_created_at", "practice_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_practice_attempts_created_at", table_name="practice_attempts")
    op.drop_index("ix_practice_attempts_question_id", table_name="practice_attempts")
    op.drop_table("practice_attempts")
    op.drop_column("study_progress", "correct_streak")

"""add study_progress table

Revision ID: 005
Revises: 004
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_progress",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "knowledge_point_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column(
            "manual_status",
            sa.String(32),
            nullable=True,
        ),
        sa.Column(
            "quiz_correct_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "quiz_total_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "answered_question_ids",
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment="已答题目的 ID 列表（用于去重）",
        ),
        sa.Column(
            "last_reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # ── CHECK 约束 ────────────────────────────
        sa.CheckConstraint(
            "status IN ('not_started','in_progress','mastered','struggling')",
            name="ck_sp_status_valid",
        ),
        sa.CheckConstraint(
            "manual_status IS NULL OR manual_status IN "
            "('not_started','in_progress','mastered','struggling')",
            name="ck_sp_manual_status_valid",
        ),
    )

    # UNIQUE 约束：每个知识点只有一条进度记录
    op.create_unique_constraint(
        "uq_study_progress_kp_id",
        "study_progress",
        ["knowledge_point_id"],
    )

    # 索引
    op.create_index(
        "ix_study_progress_status",
        "study_progress",
        ["status"],
    )
    op.create_index(
        "ix_study_progress_updated_at",
        "study_progress",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_progress_updated_at", table_name="study_progress")
    op.drop_index("ix_study_progress_status", table_name="study_progress")
    op.drop_unique_constraint("uq_study_progress_kp_id", table_name="study_progress")
    op.drop_table("study_progress")

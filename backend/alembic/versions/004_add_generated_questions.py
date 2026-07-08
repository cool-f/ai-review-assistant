"""add generated_questions and question_knowledge_points tables

Revision ID: 004
Revises: 003
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. 创建 generated_questions 表 ──────────
    op.create_table(
        "generated_questions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "courseware_id",
            UUID(as_uuid=False),
            sa.ForeignKey("coursewares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_type",
            sa.String(32),
            nullable=False,
            server_default="选择题",
            comment="选择题 | 填空题 | 计算题 | 证明题",
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", JSONB, nullable=True, comment="选择题选项 JSON 数组"),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "source_style",
            sa.String(32),
            nullable=False,
            server_default="ai_generated",
            comment="from_example | ai_generated",
        ),
        sa.Column(
            "difficulty",
            sa.String(16),
            nullable=False,
            server_default="中等",
            comment="简单 | 中等 | 困难",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 索引
    op.create_index(
        "ix_generated_questions_courseware_id",
        "generated_questions",
        ["courseware_id"],
    )
    op.create_index(
        "ix_generated_questions_kp_id",
        "generated_questions",
        ["knowledge_point_id"],
    )
    op.create_index(
        "ix_generated_questions_created_at",
        "generated_questions",
        ["created_at"],
    )

    # ── 2. 创建 question_knowledge_points 关联表 ──
    op.create_table(
        "question_knowledge_points",
        sa.Column(
            "question_id",
            UUID(as_uuid=False),
            sa.ForeignKey("generated_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("question_id", "knowledge_point_id"),
    )

    op.create_index(
        "ix_qkp_knowledge_point_id",
        "question_knowledge_points",
        ["knowledge_point_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_qkp_knowledge_point_id", table_name="question_knowledge_points")
    op.drop_table("question_knowledge_points")
    op.drop_index("ix_generated_questions_created_at", table_name="generated_questions")
    op.drop_index("ix_generated_questions_kp_id", table_name="generated_questions")
    op.drop_index(
        "ix_generated_questions_courseware_id", table_name="generated_questions"
    )
    op.drop_table("generated_questions")

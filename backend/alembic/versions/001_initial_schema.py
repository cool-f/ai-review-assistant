"""
初始迁移：创建全部 10 张表 + pgvector 扩展 + 索引

Revision ID: 001
Revises: None
Create Date: 2026-06-27
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

# ── revision identifiers ─────────────────────────
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建所有表"""

    # ── 启用 pgvector 扩展 ─────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ═══════════════════════════════════════════════
    # 表 1: coursewares
    # ═══════════════════════════════════════════════
    op.create_table(
        "coursewares",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("file_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("file_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
            comment="pending | processing | completed | failed",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 2: knowledge_points
    # ═══════════════════════════════════════════════
    op.create_table(
        "knowledge_points",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "courseware_id",
            UUID(as_uuid=False),
            sa.ForeignKey("coursewares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 3: examples
    # ═══════════════════════════════════════════════
    op.create_table(
        "examples",
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
            sa.ForeignKey("knowledge_points.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 4: homeworks
    # ═══════════════════════════════════════════════
    op.create_table(
        "homeworks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("file_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("file_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
            comment="pending | processing | completed | failed",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 5: solutions
    # ═══════════════════════════════════════════════
    op.create_table(
        "solutions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "homework_id",
            UUID(as_uuid=False),
            sa.ForeignKey("homeworks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("thinking_process", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 6: solution_knowledge_points
    # ═══════════════════════════════════════════════
    op.create_table(
        "solution_knowledge_points",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "solution_id",
            UUID(as_uuid=False),
            sa.ForeignKey("solutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "match_method",
            sa.String(64),
            nullable=False,
            server_default="auto",
            comment="auto | manual | hybrid",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("solution_id", "knowledge_point_id", name="uq_skp_sid_kpid"),
    )

    # ═══════════════════════════════════════════════
    # 表 7: chunks
    # ═══════════════════════════════════════════════
    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "courseware_id",
            UUID(as_uuid=False),
            sa.ForeignKey("coursewares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("courseware_id", "chunk_index", name="uq_chunk_cid_idx"),
    )

    # ═══════════════════════════════════════════════
    # 表 8: knowledge_point_links
    # ═══════════════════════════════════════════════
    op.create_table(
        "knowledge_point_links",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "source_kp_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_kp_id",
            UUID(as_uuid=False),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "link_type",
            sa.String(64),
            nullable=False,
            server_default="related",
            comment="prerequisite | extends | related",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_kp_id <> target_kp_id",
            name="ck_kpl_no_self_loop",
        ),
        sa.UniqueConstraint("source_kp_id", "target_kp_id", name="uq_kpl_src_tgt"),
    )

    # ═══════════════════════════════════════════════
    # 表 9: chat_sessions
    # ═══════════════════════════════════════════════
    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column(
            "courseware_id",
            UUID(as_uuid=False),
            sa.ForeignKey("coursewares.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ═══════════════════════════════════════════════
    # 表 10: chat_messages
    # ═══════════════════════════════════════════════
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default="user",
            comment="user | assistant | system",
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_cm_role_valid",
        ),
    )

    # ── 常规 B-Tree 索引 ────────────────────────
    op.create_index("ix_coursewares_status", "coursewares", ["status"])
    op.create_index("ix_coursewares_created_at", "coursewares", ["created_at"])
    op.create_index("ix_kp_courseware_id", "knowledge_points", ["courseware_id"])
    op.create_index("ix_examples_courseware_id", "examples", ["courseware_id"])
    op.create_index("ix_examples_kp_id", "examples", ["knowledge_point_id"])
    op.create_index("ix_skp_solution_id", "solution_knowledge_points", ["solution_id"])
    op.create_index("ix_skp_kp_id", "solution_knowledge_points", ["knowledge_point_id"])
    op.create_index("ix_chunks_courseware_id", "chunks", ["courseware_id"])
    op.create_index("ix_kpl_source_kp_id", "knowledge_point_links", ["source_kp_id"])
    op.create_index("ix_kpl_target_kp_id", "knowledge_point_links", ["target_kp_id"])
    op.create_index("ix_cm_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_cm_created_at", "chat_messages", ["created_at"])
    op.create_index("ix_solutions_homework_id", "solutions", ["homework_id"])
    op.create_index("ix_chat_sessions_courseware_id", "chat_sessions", ["courseware_id"])

    # ── 向量索引 (IVFFlat) ──────────────────────
    # IVFFlat 要求表中有数据才能有效构建；空表上创建的索引会退化。
    # 建议在首次批量导入 embedding 后执行 REINDEX。
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_kp_embedding_ivf
        ON knowledge_points
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_examples_embedding_ivf
        ON examples
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunks_embedding_ivf
        ON chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    """回滚：删除所有表（按外键依赖逆序）"""

    # ── 回滚 B-Tree 索引 ──────────────────────────
    op.drop_index("ix_chat_sessions_courseware_id", table_name="chat_sessions")
    op.drop_index("ix_solutions_homework_id", table_name="solutions")
    op.drop_index("ix_cm_created_at", table_name="chat_messages")
    op.drop_index("ix_cm_session_id", table_name="chat_messages")
    op.drop_index("ix_kpl_target_kp_id", table_name="knowledge_point_links")
    op.drop_index("ix_kpl_source_kp_id", table_name="knowledge_point_links")
    op.drop_index("ix_chunks_courseware_id", table_name="chunks")
    op.drop_index("ix_skp_kp_id", table_name="solution_knowledge_points")
    op.drop_index("ix_skp_solution_id", table_name="solution_knowledge_points")
    op.drop_index("ix_examples_kp_id", table_name="examples")
    op.drop_index("ix_examples_courseware_id", table_name="examples")
    op.drop_index("ix_kp_courseware_id", table_name="knowledge_points")
    op.drop_index("ix_coursewares_created_at", table_name="coursewares")
    op.drop_index("ix_coursewares_status", table_name="coursewares")

    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("knowledge_point_links")
    op.drop_table("chunks")
    op.drop_table("solution_knowledge_points")
    op.drop_table("solutions")
    op.drop_table("homeworks")
    op.drop_table("examples")
    op.drop_table("knowledge_points")
    op.drop_table("coursewares")

    # 不删除 vector 扩展，避免影响同一数据库中的其他应用

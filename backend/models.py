"""
全部 15 张核心表的 SQLAlchemy ORM 模型

表清单:
  1. coursewares          — 课件
  2. knowledge_points     — 知识点 (含向量)
  3. examples             — 例题 (含向量)
  4. homeworks            — 作业
  5. solutions            — 解答
  6. solution_knowledge_points — 解答-知识点关联
  7. chunks               — 文本块 (含向量)
  8. knowledge_point_links — 知识点关联
  9. chat_sessions        — 对话会话
  10. chat_messages       — 对话消息
  11. token_usage_logs    — Token 用量记录
  12. folders             — 文件夹（课件/作业分类管理）
  13. generated_questions — AI 生成练习题
  14. question_knowledge_points — 题目-知识点关联
  15. study_progress      — 学习进度追踪
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    String,
    Text,
    Integer,
    BigInteger,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    JSON,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector


# ── 声明基类 ──────────────────────────────────────
class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """返回 UTC 当前时间"""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """生成 UUIDv4 字符串"""
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════
# 表 1: coursewares
# ═══════════════════════════════════════════════════
class Courseware(Base):
    __tablename__ = "coursewares"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
        comment="pending | processing | completed | failed"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_vision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default=text("false"),
        comment="是否使用了 Vision 识别管线"
    )
    folder_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 关系 ──────────────────────────────────
    knowledge_points = relationship(
        "KnowledgePoint", back_populates="courseware", cascade="all, delete-orphan"
    )
    examples = relationship(
        "Example", back_populates="courseware", cascade="all, delete-orphan"
    )
    chunks = relationship(
        "Chunk", back_populates="courseware", cascade="all, delete-orphan"
    )
    chat_sessions = relationship(
        "ChatSession", back_populates="courseware"
    )
    generated_questions = relationship(
        "GeneratedQuestion", back_populates="courseware", cascade="all, delete-orphan"
    )
    folder = relationship("Folder", back_populates="coursewares")

    @property
    def has_original_text(self) -> bool:
        return self.original_text is not None and len(self.original_text) > 0


# ═══════════════════════════════════════════════════
# 表 2: knowledge_points
# ═══════════════════════════════════════════════════
class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    courseware_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("coursewares.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 关系 ──────────────────────────────────
    courseware = relationship("Courseware", back_populates="knowledge_points")
    examples = relationship(
        "Example", back_populates="knowledge_point",
    )
    solution_links = relationship(
        "SolutionKnowledgePoint", back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )
    source_links = relationship(
        "KnowledgePointLink",
        back_populates="source_kp",
        foreign_keys="KnowledgePointLink.source_kp_id",
        cascade="all, delete-orphan",
    )
    target_links = relationship(
        "KnowledgePointLink",
        back_populates="target_kp",
        foreign_keys="KnowledgePointLink.target_kp_id",
        cascade="all, delete-orphan",
    )
    generated_questions = relationship(
        "GeneratedQuestion", back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )
    progress = relationship(
        "StudyProgress", back_populates="knowledge_point",
        uselist=False, cascade="all, delete-orphan",
    )


# ═══════════════════════════════════════════════════
# 表 3: examples
# ═══════════════════════════════════════════════════
class Example(Base):
    __tablename__ = "examples"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    courseware_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("coursewares.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="SET NULL"),
        nullable=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 关系 ──────────────────────────────────
    courseware = relationship("Courseware", back_populates="examples")
    knowledge_point = relationship("KnowledgePoint", back_populates="examples")


# ═══════════════════════════════════════════════════
# 表 4: homeworks
# ═══════════════════════════════════════════════════
class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
        comment="pending | processing | completed | failed"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 关系 ──────────────────────────────────
    solutions = relationship(
        "Solution", back_populates="homework", cascade="all, delete-orphan"
    )
    folder = relationship("Folder", back_populates="homeworks")


# ═══════════════════════════════════════════════════
# 表 5: solutions
# ═══════════════════════════════════════════════════
class Solution(Base):
    __tablename__ = "solutions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    homework_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("homeworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking_process: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 索引 ──────────────────────────────────
    __table_args__ = (
        Index("ix_solutions_homework_id", "homework_id"),
    )

    # ── 关系 ──────────────────────────────────
    homework = relationship("Homework", back_populates="solutions")
    knowledge_point_links = relationship(
        "SolutionKnowledgePoint", back_populates="solution",
        cascade="all, delete-orphan",
    )


# ═══════════════════════════════════════════════════
# 表 6: solution_knowledge_points
# ═══════════════════════════════════════════════════
class SolutionKnowledgePoint(Base):
    __tablename__ = "solution_knowledge_points"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    solution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("solutions.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_method: Mapped[str] = mapped_column(
        String(64), nullable=False, default="auto",
        comment="auto | manual | hybrid"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 约束 ──────────────────────────────────
    __table_args__ = (
        UniqueConstraint("solution_id", "knowledge_point_id", name="uq_skp_sid_kpid"),
    )

    # ── 关系 ──────────────────────────────────
    solution = relationship("Solution", back_populates="knowledge_point_links")
    knowledge_point = relationship("KnowledgePoint", back_populates="solution_links")


# ═══════════════════════════════════════════════════
# 表 7: chunks
# ═══════════════════════════════════════════════════
class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    courseware_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("coursewares.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 约束 ──────────────────────────────────
    __table_args__ = (
        UniqueConstraint("courseware_id", "chunk_index", name="uq_chunk_cid_idx"),
    )

    # ── 关系 ──────────────────────────────────
    courseware = relationship("Courseware", back_populates="chunks")


# ═══════════════════════════════════════════════════
# 表 8: knowledge_point_links
# ═══════════════════════════════════════════════════
class KnowledgePointLink(Base):
    __tablename__ = "knowledge_point_links"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    source_kp_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_kp_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    link_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="related",
        comment="prerequisite | extends | related"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 约束 ──────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "source_kp_id <> target_kp_id",
            name="ck_kpl_no_self_loop",
        ),
        UniqueConstraint("source_kp_id", "target_kp_id", name="uq_kpl_src_tgt"),
    )

    # ── 关系 ──────────────────────────────────
    source_kp = relationship(
        "KnowledgePoint",
        back_populates="source_links",
        foreign_keys=[source_kp_id],
    )
    target_kp = relationship(
        "KnowledgePoint",
        back_populates="target_links",
        foreign_keys=[target_kp_id],
    )


# ═══════════════════════════════════════════════════
# 表 9: chat_sessions
# ═══════════════════════════════════════════════════
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    courseware_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("coursewares.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 索引 ──────────────────────────────────
    __table_args__ = (
        Index("ix_chat_sessions_courseware_id", "courseware_id"),
    )

    # ── 关系 ──────────────────────────────────
    courseware = relationship("Courseware", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage", back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


# ═══════════════════════════════════════════════════
# 表 10: chat_messages
# ═══════════════════════════════════════════════════
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user",
        comment="user | assistant | system"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 约束 ──────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_cm_role_valid",
        ),
    )

    # ── 关系 ──────────────────────────────────
    session = relationship("ChatSession", back_populates="messages")


# ═══════════════════════════════════════════════════
# 表 12: folders — 课件/作业分类文件夹
# ═══════════════════════════════════════════════════
class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="courseware | homework"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 约束 ──────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "category IN ('courseware', 'homework')",
            name="ck_folder_category_valid",
        ),
        Index("ix_folders_category", "category"),
    )

    # ── 关系 ──────────────────────────────────
    coursewares = relationship(
        "Courseware", back_populates="folder"
    )
    homeworks = relationship(
        "Homework", back_populates="folder"
    )


# ═══════════════════════════════════════════════════
# 表 11: token_usage_logs
# ═══════════════════════════════════════════════════
class TokenUsageLog(Base):
    """每次 AI 调用的 Token 用量记录"""

    __tablename__ = "token_usage_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="",
        comment="anthropic | openai | qwen | deepseek"
    )
    model: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 约束与索引 ────────────────────────────
    __table_args__ = (
        Index("ix_token_usage_logs_created_at", "created_at"),
        Index("ix_token_usage_logs_provider", "provider"),
        Index("ix_token_usage_logs_session_id", "session_id"),
        CheckConstraint(
            "prompt_tokens >= 0",
            name="ck_tul_prompt_tokens_non_negative",
        ),
        CheckConstraint(
            "completion_tokens >= 0",
            name="ck_tul_completion_tokens_non_negative",
        ),
    )


# ═══════════════════════════════════════════════════
# 表 13: generated_questions — AI 生成练习题
# ═══════════════════════════════════════════════════
class GeneratedQuestion(Base):
    __tablename__ = "generated_questions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    courseware_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("coursewares.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="选择题",
        comment="选择题 | 填空题 | 计算题 | 证明题",
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_style: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_generated",
        comment="from_example | ai_generated",
    )
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default="中等",
        comment="简单 | 中等 | 困难",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ── 关系 ──────────────────────────────────
    courseware = relationship("Courseware", back_populates="generated_questions")
    knowledge_point = relationship(
        "KnowledgePoint", back_populates="generated_questions"
    )
    linked_knowledge_points = relationship(
        "QuestionKnowledgePoint", back_populates="question",
        cascade="all, delete-orphan",
    )


# ═══════════════════════════════════════════════════
# 表 14: question_knowledge_points — 题目-知识点关联
# ═══════════════════════════════════════════════════
class QuestionKnowledgePoint(Base):
    __tablename__ = "question_knowledge_points"

    question_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("generated_questions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # ── 关系 ──────────────────────────────────
    question = relationship(
        "GeneratedQuestion", back_populates="linked_knowledge_points"
    )
    knowledge_point = relationship("KnowledgePoint")


# ═══════════════════════════════════════════════════
# 表 15: study_progress — 学习进度追踪
# ═══════════════════════════════════════════════════
class StudyProgress(Base):
    """每个知识点一条进度记录（1:1 关系）"""

    __tablename__ = "study_progress"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started",
        comment="not_started | in_progress | mastered | struggling",
    )
    manual_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="用户手动设置的状态",
    )
    quiz_correct_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    quiz_total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    answered_question_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list,
        server_default=text("'[]'::jsonb"),
        comment="已答题目的 ID 列表（用于去重）",
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ── 约束与索引 ────────────────────────────
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", name="uq_study_progress_kp_id"),
        CheckConstraint(
            "status IN ('not_started','in_progress','mastered','struggling')",
            name="ck_sp_status_valid",
        ),
        CheckConstraint(
            "manual_status IS NULL OR manual_status IN "
            "('not_started','in_progress','mastered','struggling')",
            name="ck_sp_manual_status_valid",
        ),
    )

    # ── 关系 ──────────────────────────────────
    knowledge_point = relationship("KnowledgePoint", back_populates="progress")

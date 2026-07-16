"""
作业相关 Pydantic v2 Schema

包含:
  - HomeworkCreate            — 创建作业时使用的字段
  - SolutionKnowledgePointRef — 解答关联的知识点摘要
  - SolutionResponse          — 单条解答响应
  - HomeworkResponse          — 作业基本响应
  - HomeworkDetailResponse    — 作业详情 (含解答列表)
  - HomeworkListResponse      — 分页列表响应
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── 知识点引用 (嵌套在解答中) ─────────────────────
class SolutionKnowledgePointRef(BaseModel):
    """解答关联的知识点简要信息"""
    id: str
    knowledge_point_id: str
    knowledge_point_title: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    match_method: str = Field(default="keyword", max_length=64)

    model_config = ConfigDict(from_attributes=True)


# ── 解答响应 ─────────────────────────────────────
class SolutionResponse(BaseModel):
    """返回给客户端的解答对象"""
    id: str
    question_number: int = Field(..., ge=0)
    question_text: str
    answer_text: str | None = None
    thinking_process: str | None = None
    created_at: datetime
    knowledge_point_links: list[SolutionKnowledgePointRef] = []

    model_config = ConfigDict(from_attributes=True)


# ── 作业基本响应 ─────────────────────────────────
class HomeworkResponse(BaseModel):
    """返回给客户端的作业对象 (不含解答详情)"""
    id: str
    course_id: str
    title: str
    file_type: str
    file_size: int
    status: str
    error_message: str | None = None
    folder_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 作业详情响应 (含解答) ───────────────────────
class HomeworkDetailResponse(HomeworkResponse):
    """作业详情，包含所有解答及知识点关联"""
    solutions: list[SolutionResponse] = []


# ── 分页列表响应 ─────────────────────────────────
class HomeworkListResponse(BaseModel):
    """作业分页列表"""
    items: list[HomeworkResponse]
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    size: int = Field(..., ge=1, description="每页条数")
    pages: int = Field(..., ge=0, description="总页数")

"""
知识点相关 Pydantic v2 Schema

包含:
  - ExampleResponse:         例题响应
  - KnowledgePointResponse:  知识点响应（含例题列表）
  - KnowledgePointListResponse: 知识点分页列表响应
  - ExtractRequest:          提取请求
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── 例题响应 ──────────────────────────────────────
class ExampleResponse(BaseModel):
    """例题响应"""
    id: str
    courseware_id: str
    knowledge_point_id: str | None = None
    question: str
    answer: str
    explanation: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 知识点响应 ────────────────────────────────────
class KnowledgePointResponse(BaseModel):
    """知识点响应（含关联例题）"""
    id: str
    courseware_id: str
    title: str
    content: str
    page_number: int | None = None
    order_index: int = 0
    revision: int = 1
    indexing_status: str = "completed"
    indexing_error: str | None = None
    examples: list[ExampleResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 知识点列表响应 ────────────────────────────────
class KnowledgePointListResponse(BaseModel):
    """知识点分页列表"""
    items: list[KnowledgePointResponse]
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    size: int = Field(..., ge=1, description="每页条数")
    pages: int = Field(..., ge=0, description="总页数")


# ── 提取请求 ──────────────────────────────────────
class ExtractRequest(BaseModel):
    """触发知识点提取请求（可扩展）"""
    force: bool = Field(
        default=False,
        description="显式确认全量重提取；会清理该课件已有知识点及其学习记录",
    )


# ── 提取状态响应 ──────────────────────────────────
class ExtractStatusResponse(BaseModel):
    """提取操作状态响应"""
    courseware_id: str
    status: str = Field(..., description="processing | completed | failed")
    message: str = Field(default="", description="状态描述")


class KnowledgePointUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=100000)
    page_number: int | None = Field(default=None, ge=1)

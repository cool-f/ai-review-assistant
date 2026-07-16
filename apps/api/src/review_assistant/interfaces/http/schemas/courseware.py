"""
课件相关 Pydantic v2 Schema
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── 创建（内部使用） ──────────────────────────────
class CoursewareCreate(BaseModel):
    """创建课件记录时使用的字段"""
    title: str = Field(default="", max_length=512, description="课件标题")
    file_type: str = Field(..., max_length=32, description="文件类型: pdf | pptx | docx | txt | md")
    file_size: int = Field(..., description="文件大小 (bytes)")
    file_hash: str = Field(default="", max_length=128, description="SHA-256 文件哈希")


# ── 单个课件响应 ─────────────────────────────────
class CoursewareResponse(BaseModel):
    """返回给客户端的课件对象"""
    id: str
    course_id: str
    title: str
    file_type: str
    file_size: int
    status: str
    parse_status: str
    knowledge_status: str
    embedding_status: str
    linking_status: str
    failed_stage: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    page_count: int | None = None
    has_original_text: bool = False
    use_vision: bool = False
    folder_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 分页列表响应 ─────────────────────────────────
class CoursewareListResponse(BaseModel):
    """课件分页列表"""
    items: list[CoursewareResponse]
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    size: int = Field(..., ge=1, description="每页条数")
    pages: int = Field(..., ge=0, description="总页数")

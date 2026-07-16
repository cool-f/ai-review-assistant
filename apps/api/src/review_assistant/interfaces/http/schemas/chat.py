"""
聊天相关 Pydantic v2 Schema

包含:
  - ChatSessionCreate     — 创建会话请求
  - ChatSessionResponse   — 会话响应
  - ChatSessionListResponse — 会话分页列表
  - ChatMessageCreate     — 发送消息请求
  - ChatMessageResponse   — 消息响应
  - ChatHistoryResponse   — 历史消息响应
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── 会话 ──────────────────────────────────────────

class ChatSessionCreate(BaseModel):
    """创建新聊天会话"""
    title: str = Field(
        default="",
        max_length=512,
        description="会话标题，为空时自动生成",
    )
    course_id: str = Field(..., description="会话所属课程 ID")
    courseware_id: str | None = Field(
        default=None,
        description="关联的课件 ID，选中后 AI 可引用课件知识点",
    )


class ChatSessionResponse(BaseModel):
    """返回给客户端的会话对象"""
    id: str
    course_id: str
    title: str
    courseware_id: str | None = None
    message_count: int = Field(
        default=0,
        description="该会话的消息总数",
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionListResponse(BaseModel):
    """会话分页列表"""
    items: list[ChatSessionResponse]
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    size: int = Field(..., ge=1, description="每页条数")
    pages: int = Field(..., ge=0, description="总页数")


# ── 消息 ──────────────────────────────────────────

class ChatMessageCreate(BaseModel):
    """发送消息请求"""
    content: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="用户消息内容",
    )
    idempotency_key: str = Field(..., min_length=16, max_length=128)


class ChatMessageResponse(BaseModel):
    """返回给客户端的消息对象"""
    id: str
    session_id: str
    role: str  # user | assistant | system
    content: str
    token_count: int = 0
    citations: list[dict] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryResponse(BaseModel):
    """会话历史消息列表"""
    session_id: str
    messages: list[ChatMessageResponse]
    total: int = Field(..., ge=0, description="消息总数")

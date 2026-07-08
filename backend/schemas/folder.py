"""
文件夹相关 Pydantic v2 Schema
"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# ── 创建文件夹 ──────────────────────────────────────
class FolderCreate(BaseModel):
    """创建文件夹请求"""
    name: str = Field(..., min_length=1, max_length=100, description="文件夹名称")
    category: Literal["courseware", "homework"] = Field(
        ..., description="分类: courseware (课件) | homework (作业)"
    )


# ── 重命名文件夹 ────────────────────────────────────
class FolderUpdate(BaseModel):
    """重命名文件夹请求"""
    name: str = Field(..., min_length=1, max_length=100, description="新名称")


# ── 单个文件夹响应 ─────────────────────────────────
class FolderResponse(BaseModel):
    """返回给客户端的文件夹对象"""
    id: str
    name: str
    category: str
    courseware_count: int = 0
    homework_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 文件夹列表响应 ─────────────────────────────────
class FolderListResponse(BaseModel):
    """文件夹列表"""
    items: list[FolderResponse]
    total: int = Field(..., ge=0)


# ── 移动条目 ────────────────────────────────────────
class MoveItemRequest(BaseModel):
    """移动课件/作业到文件夹"""
    item_id: str = Field(..., description="课件或作业的 ID")
    item_type: Literal["courseware", "homework"] = Field(
        ..., description="条目类型"
    )
    folder_id: str | None = Field(
        default=None, description="目标文件夹 ID，None 表示移到根目录"
    )


class MoveItemResponse(BaseModel):
    """移动操作响应"""
    item_id: str
    item_type: str
    folder_id: str | None = None

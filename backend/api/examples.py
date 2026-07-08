"""
例题 API 路由

端点:
  GET /api/knowledge-points/{kp_id}/examples — 获取指定知识点的例题列表
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import KnowledgePoint, Example
from backend.schemas.example import ExampleResponse, ExampleListResponse

logger = logging.getLogger(__name__)

# ── 路由器 ──────────────────────────────────────────
# 注意：此路由与 kp_router (prefix="/api/knowledge-points") 共享前缀，
# FastAPI 通过路径段数区分 /{kp_id} 与 /{kp_id}/examples，不会冲突。
examples_router = APIRouter(
    prefix="/api/knowledge-points",
    tags=["examples"],
)


# ═══════════════════════════════════════════════════
# 路由处理器
# ═══════════════════════════════════════════════════

@examples_router.get(
    "/{kp_id}/examples",
    response_model=ExampleListResponse,
    summary="获取知识点例题列表",
    description="返回指定知识点下的所有例题，支持分页。",
)
async def list_examples(
    kp_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=50, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定知识点的例题分页列表

    - 验证知识点存在
    - 返回该知识点关联的所有例题
    """
    # 验证知识点存在
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == kp_id)
    )
    if not kp_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="知识点不存在")

    # 查询总数
    count_result = await db.execute(
        select(func.count(Example.id)).where(
            Example.knowledge_point_id == kp_id
        )
    )
    total = count_result.scalar() or 0

    # 分页查询例题
    offset = (page - 1) * size
    result = await db.execute(
        select(Example)
        .where(Example.knowledge_point_id == kp_id)
        .order_by(Example.created_at)
        .offset(offset)
        .limit(size)
    )
    examples = list(result.scalars().all())

    return ExampleListResponse(
        examples=examples,
        knowledge_point_id=kp_id,
        total=total,
    )

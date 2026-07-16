"""
知识点关联查询 API 路由

端点:
  GET /api/knowledge-points/{kp_id}/links    — 查看某知识点所有双向关联
  GET /api/coursewares/{courseware_id}/cross-links — 查看课件跨课件关联
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import KnowledgePoint, KnowledgePointLink, Courseware
from review_assistant.interfaces.http.schemas.link import (
    KnowledgePointLinkResponse,
    KnowledgePointLinksResponse,
    CoursewareCrossLinksResponse,
    LinkedKnowledgePointBrief,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["knowledge-point-links"])


# ═══════════════════════════════════════════════════════
# GET /api/knowledge-points/{kp_id}/links
# ═══════════════════════════════════════════════════════
@router.get(
    "/knowledge-points/{kp_id}/links",
    response_model=KnowledgePointLinksResponse,
)
async def get_knowledge_point_links(
    kp_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取某知识点的所有双向关联（source 或 target 为该 KP 的关联记录）

    返回的每条 link 包含 linked_kp 字段，表示关联对方知识点的简要信息
    （id, title, courseware_id），方便前端直接展示。

    关联记录按相似度降序排列。
    """
    # ── 1. 验证知识点存在 ─────────────────────────
    kp_result = await db.execute(
        select(KnowledgePoint)
        .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
        .where(KnowledgePoint.id == kp_id, Courseware.course_id == course_id)
    )
    kp = kp_result.scalar_one_or_none()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    # ── 2. 查询双向关联 ───────────────────────────
    # source_kp_id = kp_id OR target_kp_id = kp_id
    result = await db.execute(
        select(KnowledgePointLink)
        .where(
            or_(
                KnowledgePointLink.source_kp_id == kp_id,
                KnowledgePointLink.target_kp_id == kp_id,
            )
        )
        .order_by(KnowledgePointLink.similarity.desc())
    )
    links = list(result.scalars().all())

    # ── 3. 收集对方 KP ID，批量查询基本信息 ──────────
    linked_kp_ids: set[str] = set()
    for link in links:
        if link.source_kp_id == kp_id:
            linked_kp_ids.add(link.target_kp_id)
        else:
            linked_kp_ids.add(link.source_kp_id)

    kp_info_map: dict[str, LinkedKnowledgePointBrief] = {}
    if linked_kp_ids:
        kp_info_result = await db.execute(
            select(KnowledgePoint.id, KnowledgePoint.title, KnowledgePoint.courseware_id, Courseware.title.label("courseware_title"))
            .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
            .where(KnowledgePoint.id.in_(list(linked_kp_ids)), Courseware.course_id == course_id)
        )
        for row in kp_info_result:
            kp_info_map[row.id] = LinkedKnowledgePointBrief(
                id=row.id,
                title=row.title,
                courseware_id=row.courseware_id,
                courseware_title=row.courseware_title,
            )

    # ── 4. 构造响应 ───────────────────────────────
    link_responses: list[KnowledgePointLinkResponse] = []
    for link in links:
        other_id = (
            link.target_kp_id
            if link.source_kp_id == kp_id
            else link.source_kp_id
        )
        link_resp = KnowledgePointLinkResponse(
            id=link.id,
            source_kp_id=link.source_kp_id,
            target_kp_id=link.target_kp_id,
            similarity=link.similarity,
            link_type=link.link_type,
            created_at=link.created_at,
            linked_kp=kp_info_map.get(other_id),
        )
        if link_resp.linked_kp is not None:
            link_responses.append(link_resp)

    return KnowledgePointLinksResponse(
        kp_id=kp_id,
        links=link_responses,
        total=len(link_responses),
    )


# ═══════════════════════════════════════════════════════
# GET /api/coursewares/{courseware_id}/cross-links
# ═══════════════════════════════════════════════════════
@router.get(
    "/coursewares/{courseware_id}/cross-links",
    response_model=CoursewareCrossLinksResponse,
)
async def get_courseware_cross_links(
    courseware_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取课件的跨课件知识点关联

    即本课件中的知识点与其他课件中知识点之间的关联。
    返回每条关联记录及关联对方知识点的简要信息，按相似度降序排列。

    这有助于发现课件之间的交叉引用和知识衔接关系。
    """
    # ── 1. 验证课件存在 ───────────────────────────
    cw_result = await db.execute(
        select(Courseware).where(Courseware.id == courseware_id, Courseware.course_id == course_id)
    )
    if not cw_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="课件不存在")

    # ── 2. 获取本课件所有知识点 ID ─────────────────
    kp_ids_result = await db.execute(
        select(KnowledgePoint.id).where(
            KnowledgePoint.courseware_id == courseware_id
        )
    )
    own_kp_ids = {row.id for row in kp_ids_result}

    if not own_kp_ids:
        return CoursewareCrossLinksResponse(
            courseware_id=courseware_id,
            cross_links=[],
            total=0,
        )

    # ── 3. 查询跨课件关联 ─────────────────────────
    # 关联中有一方在 own_kp_ids 中，另一方不在
    # 先查所有候选（source 或 target 在 own_kp_ids 中）
    result = await db.execute(
        select(KnowledgePointLink)
        .where(
            or_(
                KnowledgePointLink.source_kp_id.in_(own_kp_ids),
                KnowledgePointLink.target_kp_id.in_(own_kp_ids),
            )
        )
        .order_by(KnowledgePointLink.similarity.desc())
    )
    all_links = list(result.scalars().all())

    # ── 4. 过滤：保留跨课件关联 ────────────────────
    cross_links: list[KnowledgePointLink] = []
    linked_kp_ids: set[str] = set()
    for link in all_links:
        source_is_own = link.source_kp_id in own_kp_ids
        target_is_own = link.target_kp_id in own_kp_ids
        # 跨课件 = 一方在 own，另一方不在
        if source_is_own != target_is_own:
            cross_links.append(link)
            # 收集对方 KP ID
            if source_is_own:
                linked_kp_ids.add(link.target_kp_id)
            else:
                linked_kp_ids.add(link.source_kp_id)

    # ── 5. 批量查询对方 KP 基本信息 ─────────────────
    kp_info_map: dict[str, LinkedKnowledgePointBrief] = {}
    if linked_kp_ids:
        kp_info_result = await db.execute(
            select(KnowledgePoint.id, KnowledgePoint.title, KnowledgePoint.courseware_id, Courseware.title.label("courseware_title"))
            .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
            .where(KnowledgePoint.id.in_(list(linked_kp_ids)), Courseware.course_id == course_id)
        )
        for row in kp_info_result:
            kp_info_map[row.id] = LinkedKnowledgePointBrief(
                id=row.id,
                title=row.title,
                courseware_id=row.courseware_id,
                courseware_title=row.courseware_title,
            )

    # ── 6. 构造响应 ───────────────────────────────
    link_responses: list[KnowledgePointLinkResponse] = []
    for link in cross_links:
        # 对方 KP 是不在 own_kp_ids 中的那个
        other_id = (
            link.target_kp_id
            if link.source_kp_id in own_kp_ids
            else link.source_kp_id
        )
        link_resp = KnowledgePointLinkResponse(
            id=link.id,
            source_kp_id=link.source_kp_id,
            target_kp_id=link.target_kp_id,
            similarity=link.similarity,
            link_type=link.link_type,
            created_at=link.created_at,
            linked_kp=kp_info_map.get(other_id),
        )
        if link_resp.linked_kp is not None:
            link_responses.append(link_resp)

    return CoursewareCrossLinksResponse(
        courseware_id=courseware_id,
        cross_links=link_responses,
        total=len(link_responses),
    )

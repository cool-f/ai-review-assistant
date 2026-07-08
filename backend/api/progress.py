"""
复习进度 API 路由

端点:
  GET    /api/coursewares/{courseware_id}/progress      — 课件下所有知识点进度
  GET    /api/knowledge-points/{kp_id}/progress          — 单个知识点进度
  PATCH  /api/knowledge-points/{kp_id}/progress          — 更新进度 (mark_status / submit_answer)
  GET    /api/progress/overall                           — 全局汇总
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, case, cast, type_coerce
from sqlalchemy.dialects.postgresql import insert as pg_insert, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import KnowledgePoint, StudyProgress, Courseware

router = APIRouter(prefix="/api", tags=["progress"])


# ═══════════════════════════════════════════════════════
# 状态机常量
# ═══════════════════════════════════════════════════════

VALID_STATUSES = {"not_started", "in_progress", "mastered", "struggling"}


# ═══════════════════════════════════════════════════════
# 内联 Pydantic Schema
# ═══════════════════════════════════════════════════════

class StudyProgressResponse(BaseModel):
    """学习进度响应"""
    knowledge_point_id: str
    status: str = "not_started"
    manual_status: str | None = None
    quiz_correct_count: int = 0
    quiz_total_count: int = 0
    answered_question_count: int = 0
    last_reviewed_at: str | None = None
    updated_at: str | None = None


class CoursewareProgressResponse(BaseModel):
    """课件进度汇总响应"""
    items: list[StudyProgressResponse]
    mastered_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    struggling_count: int = 0
    total_count: int = 0


class ProgressUpdateRequest(BaseModel):
    """进度更新请求"""
    action: str = Field(..., description="mark_status | submit_answer")
    manual_status: str | None = Field(
        default=None,
        description="手动状态: not_started | in_progress | mastered | struggling",
    )
    correct: bool | None = Field(
        default=None,
        description="答题是否正确",
    )
    question_id: str | None = Field(
        default=None,
        description=(
            "题目 ID（submit_answer 时使用）。相同 question_id 的提交只累计一次，"
            "对同一题的重复提交不会影响状态"
        ),
    )


class CoursewareProgressItem(BaseModel):
    """全局汇总中的课件条目"""
    courseware_id: str
    title: str
    mastered: int = 0
    total: int = 0
    in_progress: int = 0
    not_started: int = 0
    struggling: int = 0


class OverallProgressResponse(BaseModel):
    """全局进度汇总"""
    total_knowledge_points: int = 0
    mastered_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    struggling_count: int = 0
    coursewares: list[CoursewareProgressItem] = []


# ═══════════════════════════════════════════════════════
# 状态机逻辑（纯函数，便于测试）
# ═══════════════════════════════════════════════════════

def compute_status_from_quiz(
    correct_count: int,
    total_count: int,
    manual_status: str | None = None,
) -> str:
    """根据答题情况计算状态（manual_status 存在时不自动覆盖）

    阈值语义:
      - 答对 ≥ 3 题       → mastered
      - 答对 ≥ 1 题且 < 3 → in_progress
      - 答过但全错         → struggling
      - 未答               → not_started
    """
    if manual_status is not None:
        return manual_status

    if total_count == 0:
        return "not_started"

    if correct_count >= 3:
        return "mastered"

    if correct_count >= 1:
        return "in_progress"

    # 答过题但全错 → struggling
    return "struggling"


# ═══════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════

def _build_default_progress(kp_id: str) -> StudyProgressResponse:
    """为一个没有进度记录的 KP 构建默认响应"""
    return StudyProgressResponse(knowledge_point_id=kp_id)


def _to_response(sp: StudyProgress | None) -> StudyProgressResponse:
    """ORM 对象 → 响应模型"""
    if sp is None:
        raise ValueError("sp must not be None")
    answered = sp.answered_question_ids or []
    return StudyProgressResponse(
        knowledge_point_id=sp.knowledge_point_id,
        status=sp.status,
        manual_status=sp.manual_status,
        quiz_correct_count=sp.quiz_correct_count,
        quiz_total_count=sp.quiz_total_count,
        answered_question_count=len(answered),
        last_reviewed_at=sp.last_reviewed_at.isoformat() if sp.last_reviewed_at else None,
        updated_at=sp.updated_at.isoformat() if sp.updated_at else None,
    )


async def _get_or_default(
    db: AsyncSession, kp_id: str
) -> StudyProgressResponse:
    """获取单个 KP 进度记录，无记录返回默认值（不写入 DB）"""
    stmt = select(StudyProgress).where(
        StudyProgress.knowledge_point_id == kp_id
    )
    result = await db.execute(stmt)
    sp = result.scalar_one_or_none()
    return _to_response(sp) if sp else _build_default_progress(kp_id)


# ═══════════════════════════════════════════════════════
# 原生 UPSERT（避免 SELECT-then-INSERT 竞态）
# ═══════════════════════════════════════════════════════

async def _upsert_progress(
    db: AsyncSession,
    kp_id: str,
    *,
    manual_status: str | None = None,
    quiz_correct: bool | None = None,
    question_id: str | None = None,
) -> StudyProgressResponse:
    """使用 INSERT ... ON CONFLICT DO UPDATE 进行原子 upsert。

    所有计数器增量使用 SQL 表达式（而非 Python 计算值），杜绝 SELECT-then-INSERT
    竞态。行级锁保证第二个并发事务看到第一个事务的更新后值。

    - mark_status 路径:  仅写 manual_status 与 status
    - submit_answer 路径: 数据库层面按 question_id 去重后累加计数，状态机在 SQL 中计算
    """
    if manual_status is not None and manual_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"无效状态: {manual_status}，有效值: {', '.join(sorted(VALID_STATUSES))}",
        )

    now = datetime.now(timezone.utc)

    # ── 构建 SET 子句（全部使用 SQL 表达式） ──
    set_: dict[str, Any] = {
        "last_reviewed_at": now,
        "updated_at": now,
    }

    # 用于状态计算的表达式（在 submit_answer 分支中定义）
    new_correct_expr: Any = None
    new_total_expr: Any = None

    if manual_status is not None:
        # mark_status: 简单覆盖，无竞态（last write wins）
        set_["manual_status"] = manual_status
        set_["status"] = manual_status

    elif quiz_correct is not None:
        # submit_answer: SQL 级原子累加
        if question_id is not None:
            # 带去重：数据库层面检查 question_id 是否已在 JSONB 数组中
            # 使用 @> 运算符检查包含关系
            already_answered = StudyProgress.answered_question_ids.contains(
                type_coerce([question_id], JSONB)
            )
            new_correct_expr = case(
                (already_answered, StudyProgress.quiz_correct_count),
                else_=StudyProgress.quiz_correct_count + (1 if quiz_correct else 0),
            )
            new_total_expr = case(
                (already_answered, StudyProgress.quiz_total_count),
                else_=StudyProgress.quiz_total_count + 1,
            )
            set_["quiz_correct_count"] = new_correct_expr
            set_["quiz_total_count"] = new_total_expr
            # 仅在未答过时追加 question_id（使用 || 运算符拼接 JSONB 数组）
            set_["answered_question_ids"] = case(
                (already_answered, StudyProgress.answered_question_ids),
                else_=StudyProgress.answered_question_ids.op("||")(
                    type_coerce([question_id], JSONB)
                ),
            )
        else:
            # 无去重：直接 SQL 级累加
            new_correct_expr = StudyProgress.quiz_correct_count + (1 if quiz_correct else 0)
            new_total_expr = StudyProgress.quiz_total_count + 1
            set_["quiz_correct_count"] = new_correct_expr
            set_["quiz_total_count"] = new_total_expr

        # 状态机在 SQL 中计算（基于新值表达式，由 PostgreSQL 行级锁保证一致性）
        set_["status"] = case(
            (StudyProgress.manual_status.isnot(None), StudyProgress.manual_status),
            (new_total_expr == 0, "not_started"),
            (new_correct_expr >= 3, "mastered"),
            (new_correct_expr >= 1, "in_progress"),
            else_="struggling",
        )

    # ── 构建 INSERT 默认值（用于行不存在时） ──
    insert_values: dict[str, Any] = {
        "knowledge_point_id": kp_id,
        "status": "not_started",
        "manual_status": None,
        "quiz_correct_count": 0,
        "quiz_total_count": 0,
        "answered_question_ids": [],
        "last_reviewed_at": now,
        "updated_at": now,
    }

    upsert_stmt = (
        pg_insert(StudyProgress)
        .values(**insert_values)
        .on_conflict_do_update(
            index_elements=["knowledge_point_id"],
            set_=set_,
        )
        .returning(StudyProgress)
    )

    result = await db.execute(upsert_stmt)
    sp = result.scalar_one()
    return _to_response(sp)


# ═══════════════════════════════════════════════════════
# 端点 1: 课件下所有知识点进度
# ═══════════════════════════════════════════════════════

@router.get(
    "/coursewares/{courseware_id}/progress",
    response_model=CoursewareProgressResponse,
    summary="课件知识点进度",
    description="查询课件下所有知识点的学习进度，无记录的返回默认 not_started（不写入 DB）。",
)
async def get_courseware_progress(
    courseware_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取课件所有 KP 进度"""
    # 先确认课件存在
    cw_stmt = select(Courseware).where(Courseware.id == courseware_id)
    if (await db.execute(cw_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="课件不存在")

    # 查询所有 KP
    kp_stmt = (
        select(KnowledgePoint)
        .where(KnowledgePoint.courseware_id == courseware_id)
        .order_by(KnowledgePoint.order_index)
    )
    kps = (await db.execute(kp_stmt)).scalars().all()

    if not kps:
        return CoursewareProgressResponse(
            items=[],
            mastered_count=0,
            in_progress_count=0,
            not_started_count=0,
            struggling_count=0,
            total_count=0,
        )

    # 批量查询进度记录
    kp_ids = [kp.id for kp in kps]
    sp_stmt = select(StudyProgress).where(
        StudyProgress.knowledge_point_id.in_(kp_ids)
    )
    progress_map: dict[str, StudyProgress] = {
        sp.knowledge_point_id: sp
        for sp in (await db.execute(sp_stmt)).scalars().all()
    }

    # 构建响应 + 状态计数
    items: list[StudyProgressResponse] = []
    counts = {
        "mastered": 0,
        "in_progress": 0,
        "not_started": 0,
        "struggling": 0,
    }
    for kp in kps:
        sp = progress_map.get(kp.id)
        if sp is None:
            items.append(_build_default_progress(kp.id))
            counts["not_started"] += 1
        else:
            items.append(_to_response(sp))
            counts[sp.status] = counts.get(sp.status, 0) + 1

    return CoursewareProgressResponse(
        items=items,
        mastered_count=counts["mastered"],
        in_progress_count=counts["in_progress"],
        not_started_count=counts["not_started"],
        struggling_count=counts["struggling"],
        total_count=len(kps),
    )


# ═══════════════════════════════════════════════════════
# 端点 2: 单个知识点进度
# ═══════════════════════════════════════════════════════

@router.get(
    "/knowledge-points/{kp_id}/progress",
    response_model=StudyProgressResponse,
    summary="单个知识点进度",
    description="获取单个知识点的学习进度，无记录返回默认 not_started（不写入 DB）。",
)
async def get_knowledge_point_progress(
    kp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个 KP 进度"""
    kp_stmt = select(KnowledgePoint).where(KnowledgePoint.id == kp_id)
    if (await db.execute(kp_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="知识点不存在")

    return await _get_or_default(db, kp_id)


# ═══════════════════════════════════════════════════════
# 端点 3: 更新进度
# ═══════════════════════════════════════════════════════

@router.patch(
    "/knowledge-points/{kp_id}/progress",
    response_model=StudyProgressResponse,
    summary="更新学习进度",
    description=(
        "支持两种 action:\n"
        "- mark_status: 手动标记状态 (manual_status 覆盖 status)\n"
        "- submit_answer: 提交答题结果，自动计算 status（有 manual_status 时不自动覆盖）。"
        "提供 question_id 可对同一题去重。"
    ),
)
async def update_knowledge_point_progress(
    kp_id: str,
    body: ProgressUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新 KP 学习进度"""
    kp_stmt = select(KnowledgePoint).where(KnowledgePoint.id == kp_id)
    if (await db.execute(kp_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="知识点不存在")

    if body.action == "mark_status":
        if body.manual_status is None:
            raise HTTPException(
                status_code=422,
                detail="mark_status action 需要 manual_status 字段",
            )
        return await _upsert_progress(
            db, kp_id,
            manual_status=body.manual_status,
        )

    elif body.action == "submit_answer":
        if body.correct is None:
            raise HTTPException(
                status_code=422,
                detail="submit_answer action 需要 correct 字段",
            )
        return await _upsert_progress(
            db, kp_id,
            quiz_correct=body.correct,
            question_id=body.question_id,
        )

    else:
        raise HTTPException(
            status_code=422,
            detail=f"无效 action: {body.action}，有效值: mark_status, submit_answer",
        )


# ═══════════════════════════════════════════════════════
# 端点 4: 全局汇总
# ═══════════════════════════════════════════════════════

@router.get(
    "/progress/overall",
    response_model=OverallProgressResponse,
    summary="全局复习进度",
    description="返回所有知识点的全局学习进度汇总，按课件分组。",
)
async def get_overall_progress(
    db: AsyncSession = Depends(get_db),
):
    """全局进度汇总"""
    # ── 1. 所有课件 ──
    cw_stmt = select(Courseware).order_by(Courseware.title)
    coursewares = (await db.execute(cw_stmt)).scalars().all()

    # ── 2. 所有 KP ──
    kp_stmt = select(
        KnowledgePoint.id,
        KnowledgePoint.courseware_id,
    )
    kp_rows = (await db.execute(kp_stmt)).all()
    kp_ids = [row.id for row in kp_rows]
    kp_by_cw: dict[str, list[str]] = {}
    for row in kp_rows:
        kp_by_cw.setdefault(row.courseware_id, []).append(row.id)

    # ── 3. 所有进度记录 ──
    progress_map: dict[str, str] = {}
    if kp_ids:
        sp_stmt = select(
            StudyProgress.knowledge_point_id,
            StudyProgress.status,
        ).where(StudyProgress.knowledge_point_id.in_(kp_ids))
        for row in (await db.execute(sp_stmt)).all():
            progress_map[row.knowledge_point_id] = row.status

    # ── 4. 汇总 ──
    total = len(kp_ids)
    global_counts = {
        "mastered": 0,
        "in_progress": 0,
        "not_started": 0,
        "struggling": 0,
    }
    cw_items: list[CoursewareProgressItem] = []

    for cw in coursewares:
        cw_kp_ids = kp_by_cw.get(cw.id, [])
        counts = {
            "mastered": 0,
            "in_progress": 0,
            "not_started": 0,
            "struggling": 0,
        }
        for kid in cw_kp_ids:
            status = progress_map.get(kid, "not_started")
            counts[status] = counts.get(status, 0) + 1
            global_counts[status] = global_counts.get(status, 0) + 1

        cw_items.append(CoursewareProgressItem(
            courseware_id=cw.id,
            title=cw.title,
            mastered=counts["mastered"],
            total=len(cw_kp_ids),
            in_progress=counts["in_progress"],
            not_started=counts["not_started"],
            struggling=counts["struggling"],
        ))

    return OverallProgressResponse(
        total_knowledge_points=total,
        mastered_count=global_counts["mastered"],
        in_progress_count=global_counts["in_progress"],
        not_started_count=global_counts["not_started"],
        struggling_count=global_counts["struggling"],
        coursewares=cw_items,
    )

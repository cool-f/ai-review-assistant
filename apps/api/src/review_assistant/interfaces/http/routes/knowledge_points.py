"""Knowledge-point HTTP endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from review_assistant.application.ingestion.pipeline import (
    plan_ingestion_retry,
    resume_extraction_pipeline,
    run_extraction_pipeline,
)
from review_assistant.application.knowledge.reindex import refresh_knowledge_point_index
from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import Courseware, KnowledgePoint
from review_assistant.interfaces.http.schemas.knowledge_point import (
    KnowledgePointResponse,
    KnowledgePointListResponse,
    ExtractRequest,
    ExtractStatusResponse,
    KnowledgePointUpdate,
)

# ── 路由器 1: 按课件操作知识点 ──────────────────
# 路径中的 {courseware_id} 由 FastAPI 自动注入到路由函数
courseware_kp_router = APIRouter(
    prefix="/api/coursewares/{courseware_id}/knowledge-points",
    tags=["knowledge-points"],
)

# ── 路由器 2: 知识点单条查询 ────────────────────
kp_router = APIRouter(
    prefix="/api/knowledge-points",
    tags=["knowledge-points"],
)


# ═══════════════════════════════════════════════════
# 路由处理器
# ═══════════════════════════════════════════════════

@courseware_kp_router.get("/", response_model=KnowledgePointListResponse)
async def list_knowledge_points(
    courseware_id: str,
    course_id: str,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定课件的知识点分页列表

    每个知识点会附带其关联的例题列表。
    """
    # 验证课件存在
    cw_result = await db.execute(
        select(Courseware).where(
            Courseware.id == courseware_id,
            Courseware.course_id == course_id,
        )
    )
    if not cw_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="课件不存在")

    if page < 1:
        page = 1
    if size < 1:
        size = 1
    if size > 100:
        size = 100

    # 查询总数
    count_result = await db.execute(
        select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.courseware_id == courseware_id
        )
    )
    total = count_result.scalar() or 0

    pages = max(1, (total + size - 1) // size) if total > 0 else 0

    # 分页查询知识点（预加载例题）
    offset = (page - 1) * size
    result = await db.execute(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.examples))
        .where(KnowledgePoint.courseware_id == courseware_id)
        .order_by(KnowledgePoint.order_index, KnowledgePoint.created_at)
        .offset(offset)
        .limit(size)
    )
    items = list(result.scalars().all())

    return KnowledgePointListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@courseware_kp_router.post("/extract", response_model=ExtractStatusResponse)
async def extract_knowledge_points(
    courseware_id: str,
    course_id: str,
    background_tasks: BackgroundTasks,
    body: ExtractRequest = ExtractRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    触发知识点 AI 提取（异步后台执行）

    - 课件必须存在且状态不能为 processing
    - 提取在后台执行，完成后自动更新课件状态
    - embedding/linking 失败只续跑失败阶段，不删除学习数据
    - 只有显式 force=true 才会清理已有知识点、例题和文本块
    """
    # 验证课件存在
    result = await db.execute(
        select(Courseware).where(
            Courseware.id == courseware_id,
            Courseware.course_id == course_id,
        ).with_for_update()
    )
    courseware = result.scalar_one_or_none()
    if not courseware:
        raise HTTPException(status_code=404, detail="课件不存在")

    if courseware.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="课件正在处理中，请等待当前任务完成后再试",
        )

    existing_count = await db.scalar(
        select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.courseware_id == courseware_id
        )
    ) or 0
    retry_plan = plan_ingestion_retry(
        force=body.force,
        status=courseware.status,
        failed_stage=courseware.failed_stage,
        has_knowledge=existing_count > 0,
    )
    if retry_plan == "force_required":
        raise HTTPException(
            status_code=409,
            detail="已有知识点和学习记录；若要全量重提取，必须明确 force=true",
        )

    # Claim the task while preserving completed stages for non-destructive retry.
    courseware.status = "processing"
    courseware.error_message = None
    courseware.failed_stage = None
    courseware.retry_count += 1
    if retry_plan == "embedding":
        courseware.embedding_status = "processing"
        courseware.linking_status = "pending"
    elif retry_plan == "linking":
        courseware.linking_status = "processing"
    else:
        courseware.parse_status = "processing"
        courseware.knowledge_status = "pending"
        courseware.embedding_status = "pending"
        courseware.linking_status = "pending"
    await db.commit()

    if retry_plan in {"embedding", "linking"}:
        background_tasks.add_task(
            resume_extraction_pipeline, courseware_id, retry_plan
        )
    else:
        background_tasks.add_task(
            run_extraction_pipeline,
            courseware_id,
            str(courseware.file_path),
            courseware.file_type,
            re_extract=retry_plan == "full",
            use_vision=courseware.use_vision,
        )

    return ExtractStatusResponse(
        courseware_id=courseware_id,
        status="processing",
        message=f"课件任务已启动（{retry_plan}），请稍后查询结果",
    )


@kp_router.get("/{kp_id}", response_model=KnowledgePointResponse)
async def get_knowledge_point(
    kp_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取单个知识点详情（含关联例题）
    """
    result = await db.execute(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.examples))
        .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
        .where(
            KnowledgePoint.id == kp_id,
            Courseware.course_id == course_id,
        )
    )
    kp = result.scalar_one_or_none()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    return kp


@kp_router.patch("/{kp_id}", response_model=KnowledgePointResponse)
async def update_knowledge_point(
    kp_id: str,
    body: KnowledgePointUpdate,
    background_tasks: BackgroundTasks,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.examples))
        .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
        .where(
            KnowledgePoint.id == kp_id,
            Courseware.course_id == course_id,
        )
    )
    kp = result.scalar_one_or_none()
    if kp is None:
        raise HTTPException(status_code=404, detail="知识点不存在")
    kp.title = body.title.strip()
    kp.content = body.content.strip()
    kp.page_number = body.page_number
    kp.revision += 1
    kp.indexing_status = "processing"
    kp.indexing_error = None
    await db.commit()
    await db.refresh(kp)
    background_tasks.add_task(refresh_knowledge_point_index, kp.id)
    return kp


# ═══════════════════════════════════════════════════
# 提取流水线（后台任务）
# ═══════════════════════════════════════════════════

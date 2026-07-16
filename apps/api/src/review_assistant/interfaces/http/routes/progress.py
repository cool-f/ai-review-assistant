from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.domain.study_progress import ProgressSnapshot, set_manual_status
from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import Courseware, KnowledgePoint, StudyProgress


router = APIRouter(prefix="/api", tags=["progress"])
VALID_STATUSES = {"not_started", "in_progress", "mastered", "struggling"}


class StudyProgressResponse(BaseModel):
    knowledge_point_id: str
    status: str = "not_started"
    manual_status: str | None = None
    quiz_correct_count: int = 0
    quiz_total_count: int = 0
    correct_streak: int = 0
    answered_question_count: int = 0
    last_reviewed_at: str | None = None
    updated_at: str | None = None


class CoursewareProgressResponse(BaseModel):
    items: list[StudyProgressResponse]
    mastered_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    struggling_count: int = 0
    total_count: int = 0


class ProgressUpdateRequest(BaseModel):
    action: str = Field(..., description="mark_status | clear_manual_status")
    manual_status: str | None = None


class CoursewareProgressItem(BaseModel):
    courseware_id: str
    title: str
    mastered: int = 0
    total: int = 0
    in_progress: int = 0
    not_started: int = 0
    struggling: int = 0


class OverallProgressResponse(BaseModel):
    total_knowledge_points: int = 0
    mastered_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    struggling_count: int = 0
    coursewares: list[CoursewareProgressItem] = []


def _default(kp_id: str) -> StudyProgressResponse:
    return StudyProgressResponse(knowledge_point_id=kp_id)


def _response(progress: StudyProgress) -> StudyProgressResponse:
    return StudyProgressResponse(
        knowledge_point_id=progress.knowledge_point_id,
        status=progress.status,
        manual_status=progress.manual_status,
        quiz_correct_count=progress.quiz_correct_count,
        quiz_total_count=progress.quiz_total_count,
        correct_streak=progress.correct_streak,
        answered_question_count=len(progress.answered_question_ids or []),
        last_reviewed_at=progress.last_reviewed_at.isoformat() if progress.last_reviewed_at else None,
        updated_at=progress.updated_at.isoformat() if progress.updated_at else None,
    )


def _snapshot(progress: StudyProgress) -> ProgressSnapshot:
    return ProgressSnapshot(
        status=progress.status,
        manual_status=progress.manual_status,
        correct_count=progress.quiz_correct_count,
        total_count=progress.quiz_total_count,
        correct_streak=progress.correct_streak,
        answered_question_ids=tuple(progress.answered_question_ids or []),
    )


def _apply(progress: StudyProgress, snapshot: ProgressSnapshot) -> None:
    progress.status = snapshot.status
    progress.manual_status = snapshot.manual_status
    progress.quiz_correct_count = snapshot.correct_count
    progress.quiz_total_count = snapshot.total_count
    progress.correct_streak = snapshot.correct_streak
    progress.answered_question_ids = list(snapshot.answered_question_ids)
    progress.last_reviewed_at = datetime.now(timezone.utc)


async def _knowledge_point_belongs_to_course(
    db: AsyncSession, kp_id: str, course_id: str
) -> bool:
    return bool(await db.scalar(
        select(KnowledgePoint.id)
        .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
        .where(
            KnowledgePoint.id == kp_id,
            Courseware.course_id == course_id,
        )
    ))


async def _get_or_create_locked(db: AsyncSession, kp_id: str) -> StudyProgress:
    result = await db.execute(
        select(StudyProgress).where(StudyProgress.knowledge_point_id == kp_id).with_for_update()
    )
    progress = result.scalar_one_or_none()
    if progress is None:
        progress = StudyProgress(knowledge_point_id=kp_id)
        db.add(progress)
        await db.flush()
    return progress


async def _lock_knowledge_point_in_course(
    db: AsyncSession, kp_id: str, course_id: str
) -> KnowledgePoint | None:
    """Serialize all first-time progress creation on the stable parent row."""
    result = await db.execute(
        select(KnowledgePoint)
        .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
        .where(
            KnowledgePoint.id == kp_id,
            Courseware.course_id == course_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


@router.get("/coursewares/{courseware_id}/progress", response_model=CoursewareProgressResponse)
async def get_courseware_progress(
    courseware_id: str, course_id: str, db: AsyncSession = Depends(get_db)
):
    courseware = await db.get(Courseware, courseware_id)
    if courseware is None or courseware.course_id != course_id:
        raise HTTPException(status_code=404, detail="课件不存在")
    kps = list((await db.execute(
        select(KnowledgePoint)
        .where(KnowledgePoint.courseware_id == courseware_id)
        .order_by(KnowledgePoint.order_index)
    )).scalars().all())
    progress_by_kp = {
        progress.knowledge_point_id: progress
        for progress in (await db.execute(
            select(StudyProgress).where(
                StudyProgress.knowledge_point_id.in_([kp.id for kp in kps])
            )
        )).scalars().all()
    } if kps else {}
    items = [_response(progress_by_kp[kp.id]) if kp.id in progress_by_kp else _default(kp.id) for kp in kps]
    counts = {status: sum(item.status == status for item in items) for status in VALID_STATUSES}
    return CoursewareProgressResponse(
        items=items,
        mastered_count=counts["mastered"],
        in_progress_count=counts["in_progress"],
        not_started_count=counts["not_started"],
        struggling_count=counts["struggling"],
        total_count=len(items),
    )


@router.get("/knowledge-points/{kp_id}/progress", response_model=StudyProgressResponse)
async def get_knowledge_point_progress(
    kp_id: str, course_id: str, db: AsyncSession = Depends(get_db)
):
    if not await _knowledge_point_belongs_to_course(db, kp_id, course_id):
        raise HTTPException(status_code=404, detail="知识点不存在")
    result = await db.execute(select(StudyProgress).where(StudyProgress.knowledge_point_id == kp_id))
    progress = result.scalar_one_or_none()
    return _response(progress) if progress else _default(kp_id)


@router.patch("/knowledge-points/{kp_id}/progress", response_model=StudyProgressResponse)
async def update_knowledge_point_progress(
    kp_id: str,
    body: ProgressUpdateRequest,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    if await _lock_knowledge_point_in_course(db, kp_id, course_id) is None:
        raise HTTPException(status_code=404, detail="知识点不存在")
    progress = await _get_or_create_locked(db, kp_id)
    current = _snapshot(progress)
    if body.action == "mark_status":
        if body.manual_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail="manual_status 无效")
        updated = set_manual_status(current, body.manual_status)
    elif body.action == "clear_manual_status":
        updated = set_manual_status(current, None)
    else:
        raise HTTPException(status_code=422, detail="action 无效")
    _apply(progress, updated)
    await db.commit()
    await db.refresh(progress)
    return _response(progress)


@router.get("/progress/overall", response_model=OverallProgressResponse)
async def get_overall_progress(course_id: str, db: AsyncSession = Depends(get_db)):
    coursewares = list((await db.execute(
        select(Courseware).where(Courseware.course_id == course_id).order_by(Courseware.title)
    )).scalars().all())
    courseware_ids = [courseware.id for courseware in coursewares]
    kp_rows = (await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.courseware_id)
        .where(KnowledgePoint.courseware_id.in_(courseware_ids))
    )).all() if courseware_ids else []
    kp_ids = [row.id for row in kp_rows]
    progress_map = {
        row.knowledge_point_id: row.status
        for row in (await db.execute(
            select(StudyProgress.knowledge_point_id, StudyProgress.status)
            .where(StudyProgress.knowledge_point_id.in_(kp_ids))
        )).all()
    } if kp_ids else {}
    kp_by_courseware: dict[str, list[str]] = {}
    for row in kp_rows:
        kp_by_courseware.setdefault(row.courseware_id, []).append(row.id)

    global_counts = {status: 0 for status in VALID_STATUSES}
    courseware_items: list[CoursewareProgressItem] = []
    for courseware in coursewares:
        ids = kp_by_courseware.get(courseware.id, [])
        counts = {status: 0 for status in VALID_STATUSES}
        for kp_id in ids:
            status = progress_map.get(kp_id, "not_started")
            counts[status] += 1
            global_counts[status] += 1
        courseware_items.append(CoursewareProgressItem(
            courseware_id=courseware.id,
            title=courseware.title,
            mastered=counts["mastered"], total=len(ids),
            in_progress=counts["in_progress"], not_started=counts["not_started"],
            struggling=counts["struggling"],
        ))
    return OverallProgressResponse(
        total_knowledge_points=len(kp_ids),
        mastered_count=global_counts["mastered"],
        in_progress_count=global_counts["in_progress"],
        not_started_count=global_counts["not_started"],
        struggling_count=global_counts["struggling"],
        coursewares=courseware_items,
    )

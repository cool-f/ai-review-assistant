from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.domain.course import CourseContents, CourseNotEmptyError
from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import (
    ChatSession,
    Course,
    Courseware,
    Folder,
    Homework,
)
from review_assistant.interfaces.http.schemas.course import CourseCreate, CourseResponse, CourseUpdate


router = APIRouter(prefix="/api/courses", tags=["courses"])


async def _response(db: AsyncSession, course: Course) -> CourseResponse:
    counts: list[int] = []
    for model in (Courseware, Homework, Folder, ChatSession):
        result = await db.execute(select(func.count(model.id)).where(model.course_id == course.id))
        counts.append(result.scalar() or 0)
    return CourseResponse(
        id=course.id, name=course.name, term=course.term, description=course.description,
        courseware_count=counts[0], homework_count=counts[1],
        folder_count=counts[2], session_count=counts[3],
        created_at=course.created_at, updated_at=course.updated_at,
    )


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(body: CourseCreate, db: AsyncSession = Depends(get_db)):
    course = Course(name=body.name.strip(), term=body.term.strip(), description=body.description.strip())
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return await _response(db, course)


@router.get("", response_model=list[CourseResponse])
async def list_courses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Course).order_by(Course.updated_at.desc()))
    return [await _response(db, course) for course in result.scalars().all()]


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(course_id: str, body: CourseUpdate, db: AsyncSession = Depends(get_db)):
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(course, key, value.strip())
    await db.commit()
    await db.refresh(course)
    return await _response(db, course)


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: str, db: AsyncSession = Depends(get_db)):
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    response = await _response(db, course)
    try:
        CourseContents(
            coursewares=response.courseware_count,
            homeworks=response.homework_count,
            folders=response.folder_count,
            sessions=response.session_count,
        ).ensure_deletable()
    except CourseNotEmptyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.delete(course)
    await db.commit()
    return None

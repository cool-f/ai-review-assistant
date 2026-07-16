"""
文件夹管理 API 路由

端点:
  POST   /api/folders/       — 创建文件夹
  GET    /api/folders/       — 按分类列出文件夹
  PATCH  /api/folders/{id}   — 重命名文件夹
  DELETE /api/folders/{id}   — 删除文件夹
  POST   /api/folders/move   — 移动条目到文件夹
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import Course, Folder, Courseware, Homework
from review_assistant.interfaces.http.schemas.folder import (
    FolderCreate,
    FolderUpdate,
    FolderResponse,
    FolderListResponse,
    MoveItemRequest,
    MoveItemResponse,
)

router = APIRouter(prefix="/api/folders", tags=["folders"])


# ── 辅助：统计文件夹内条目数 ────────────────────────
async def _count_items(db: AsyncSession, folder_id: str) -> tuple[int, int]:
    """返回 (courseware_count, homework_count)"""
    cw_result = await db.execute(
        select(func.count(Courseware.id)).where(Courseware.folder_id == folder_id)
    )
    cw_count = cw_result.scalar() or 0

    hw_result = await db.execute(
        select(func.count(Homework.id)).where(Homework.folder_id == folder_id)
    )
    hw_count = hw_result.scalar() or 0

    return cw_count, hw_count


# ══════════════════════════════════════════════════════
# POST / — 创建文件夹
# ══════════════════════════════════════════════════════
@router.post("/", response_model=FolderResponse, status_code=201)
async def create_folder(
    body: FolderCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新文件夹"""
    if await db.get(Course, body.course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    folder = Folder(name=body.name.strip(), category=body.category, course_id=body.course_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return FolderResponse(
        id=folder.id,
        course_id=folder.course_id,
        name=folder.name,
        category=folder.category,
        courseware_count=0,
        homework_count=0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ══════════════════════════════════════════════════════
# GET / — 按分类列出文件夹
# ══════════════════════════════════════════════════════
@router.get("/", response_model=FolderListResponse)
async def list_folders(
    course_id: str,
    category: str = Query(..., description="分类: courseware | homework"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定分类下的所有文件夹，按创建时间倒序"""
    if category not in ("courseware", "homework"):
        raise HTTPException(status_code=400, detail="category 必须为 courseware 或 homework")

    result = await db.execute(
        select(Folder)
        .where(Folder.category == category, Folder.course_id == course_id)
        .order_by(Folder.created_at.desc())
    )
    folders = list(result.scalars().all())

    items: list[FolderResponse] = []
    for f in folders:
        cw_count, hw_count = await _count_items(db, f.id)
        items.append(FolderResponse(
            id=f.id,
            course_id=f.course_id,
            name=f.name,
            category=f.category,
            courseware_count=cw_count,
            homework_count=hw_count,
            created_at=f.created_at,
            updated_at=f.updated_at,
        ))

    return FolderListResponse(items=items, total=len(items))


# ══════════════════════════════════════════════════════
# PATCH /{id} — 重命名文件夹
# ══════════════════════════════════════════════════════
@router.patch("/{folder_id}", response_model=FolderResponse)
async def rename_folder(
    folder_id: str,
    course_id: str,
    body: FolderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """重命名文件夹"""
    result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.course_id == course_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")

    folder.name = body.name.strip()
    await db.commit()
    await db.refresh(folder)

    cw_count, hw_count = await _count_items(db, folder_id)
    return FolderResponse(
        id=folder.id,
        course_id=folder.course_id,
        name=folder.name,
        category=folder.category,
        courseware_count=cw_count,
        homework_count=hw_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ══════════════════════════════════════════════════════
# DELETE /{id} — 删除文件夹
# ══════════════════════════════════════════════════════
@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除文件夹（其中的课件/作业的 folder_id 会被设为 NULL）"""
    result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.course_id == course_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")

    # 将文件夹内的条目移到根目录
    for model in (Courseware, Homework):
        items_result = await db.execute(
            select(model).where(model.folder_id == folder_id)
        )
        for item in items_result.scalars().all():
            item.folder_id = None

    await db.delete(folder)
    await db.commit()
    return None


# ══════════════════════════════════════════════════════
# POST /move — 移动条目到文件夹
# ══════════════════════════════════════════════════════
@router.post("/move", response_model=MoveItemResponse)
async def move_item(
    body: MoveItemRequest,
    db: AsyncSession = Depends(get_db),
):
    """将课件或作业移动到指定文件夹（或根目录）"""
    # 验证目标文件夹存在（如果不是移到根目录）
    if body.folder_id is not None:
        folder_result = await db.execute(
            select(Folder).where(Folder.id == body.folder_id, Folder.course_id == body.course_id)
        )
        folder = folder_result.scalar_one_or_none()
        if not folder:
            raise HTTPException(status_code=404, detail="目标文件夹不存在")

    # 查找并更新目标条目
    model = Courseware if body.item_type == "courseware" else Homework
    item_result = await db.execute(
        select(model).where(model.id == body.item_id, model.course_id == body.course_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"{'课件' if body.item_type == 'courseware' else '作业'}不存在",
        )

    item.folder_id = body.folder_id
    await db.commit()

    return MoveItemResponse(
        item_id=body.item_id,
        item_type=body.item_type,
        folder_id=body.folder_id,
    )

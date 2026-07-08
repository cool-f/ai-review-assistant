"""
课件管理 API 路由

端点:
  POST   /upload   — 上传课件文件
  GET    /         — 分页列表
  GET    /{id}     — 课件详情
  DELETE /{id}     — 删除课件及关联数据
"""

import hashlib
import math
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models import Courseware
from backend.schemas.courseware import (
    CoursewareResponse,
    CoursewareListResponse,
)
from backend.api.knowledge_points import run_extraction_pipeline

router = APIRouter(prefix="/api/coursewares", tags=["coursewares"])

settings = get_settings()

# 允许的文件扩展名 -> 类型映射
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
}


# ── 工具函数 ──────────────────────────────────────
def _sanitize_filename(filename: str) -> str:
    """安全化文件名：仅保留字母数字、中文、点、横线、下划线"""
    safe = "".join(
        c if c.isalnum() or c in "._-" or "一" <= c <= "鿿" else "_"
        for c in filename
    )
    if not safe or safe == "_":
        safe = "untitled"
    return safe


def _get_storage_dir(courseware_id: str) -> Path:
    """返回课件文件的存储目录"""
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    return upload_dir / "coursewares" / courseware_id


# ── POST /upload ──────────────────────────────────
@router.post("/upload", response_model=CoursewareResponse, status_code=201)
async def upload_courseware(
    file: UploadFile = File(...),
    use_vision: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    上传课件文件

    - 支持格式: pdf / pptx / docx / txt / md
    - 文件大小限制: 50 MB
    - 上传后自动提取纯文本并分块入库
    - use_vision=true 时使用视觉识别（需 Anthropic/OpenAI/Qwen 等支持 Vision 的提供商）
    """
    # ── 0. 校验 Vision 提供商 ────────────────────
    if use_vision:
        VISION_SUPPORTED = {"anthropic", "openai", "qwen"}
        if settings.AI_PROVIDER not in VISION_SUPPORTED:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"当前 AI 提供商 ({settings.AI_PROVIDER}) 不支持图片识别（Vision）。"
                    f"请在 .env 中将 AI_PROVIDER 更换为支持 Vision 的选项："
                    f"anthropic / openai / qwen"
                ),
            )
    # ── 1. 校验文件扩展名 ─────────────────────
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}。支持: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )

    file_type = ALLOWED_EXTENSIONS[ext]

    # ── 2. 读取并校验文件大小 ─────────────────
    content = await file.read()

    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超出限制 ({settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    # ── 3. 保存文件到磁盘 ─────────────────────
    cw_id = str(uuid.uuid4())
    storage_dir = _get_storage_dir(cw_id)
    storage_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(file.filename)
    file_path = storage_dir / safe_name
    file_path.write_bytes(content)

    # ── 4. 计算哈希 ───────────────────────────
    file_hash = hashlib.sha256(content).hexdigest()

    # ── 5. 标题：使用文件名（去除扩展名） ──────
    title = Path(file.filename).stem or file.filename

    # ── 6. 写入数据库记录（状态：处理中）────
    courseware = Courseware(
        id=cw_id,
        title=title,
        file_path=str(file_path),
        file_type=file_type,
        file_size=len(content),
        file_hash=file_hash,
        status="processing",
        use_vision=use_vision,
    )
    db.add(courseware)
    await db.commit()
    await db.refresh(courseware)

    # ── 7. 启动后台提取流水线 ─────────────────
    # 流水线依次执行：文本提取 → AI 知识点提取 → 嵌入向量生成 → 入库
    # 完成后自动更新课件状态为 completed / failed
    background_tasks.add_task(
        run_extraction_pipeline,
        courseware_id=cw_id,
        file_path=str(file_path),
        file_type=file_type,
        re_extract=False,  # 首次上传，不清除已有数据
        use_vision=use_vision,
    )

    return courseware


# ── POST /preflight — Token 预估 ───────────────────
@router.post("/preflight")
async def preflight_courseware(
    file: UploadFile = File(...),
):
    """
    上传前 Token 用量预估（不保存文件，不触发提取）

    - 临时提取文本内容
    - 估算 token 数和预计费用
    - 清理临时文件
    - 返回预估信息供用户确认
    """
    import tempfile
    import os

    # ── 校验扩展名 ──────────────────────────────
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}。支持: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )

    file_type = ALLOWED_EXTENSIONS[ext]

    # ── 校验大小 ────────────────────────────────
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超出限制 ({settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    # ── 临时写入并提取文本 ──────────────────────
    from backend.services.text_extractor import TextExtractor

    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
        os.close(tmp_fd)
        Path(tmp_path).write_bytes(content)

        text, page_count = TextExtractor.extract(tmp_path, file_type)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"文本提取失败: {str(e)}",
        )
    finally:
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink(missing_ok=True)

    text_len = len(text.strip()) if text else 0

    # ── 检测是否图片型 PDF ──────────────────────
    if file_type == "pdf" and page_count and page_count > 0:
        min_text_ratio = 10
        is_vision_pdf = text_len < page_count * min_text_ratio

        if is_vision_pdf:
            # 检查提供商是否支持 Vision
            VISION_SUPPORTED_PROVIDERS = {"anthropic", "openai", "qwen"}
            provider = settings.AI_PROVIDER
            if provider not in VISION_SUPPORTED_PROVIDERS:
                return {
                    "readable": False,
                    "suggested_mode": None,
                    "vision_unavailable": True,
                    "filename": file.filename,
                    "file_type": file_type,
                    "file_size_bytes": len(content),
                    "page_count": page_count,
                    "estimated_knowledge_points": 0,
                    "estimated_cost": {
                        "extraction": 0.0,
                        "embedding": 0.0,
                        "total": 0.0,
                        "currency": "USD",
                        "note": f"当前 AI 提供商 ({provider}) 不支持图片识别。",
                    },
                    "provider": provider,
                    "model": settings.AI_DEFAULT_MODEL or "默认",
                    "vision_error": f"当前 AI 提供商 ({provider}) 不支持图片识别（Vision），"
                                    f"请在 .env 中更换为支持 Vision 的提供商："
                                    f"anthropic / openai / qwen，或上传文字型 PDF",
                }

            vision_cost = _estimate_vision_cost(provider, settings.AI_DEFAULT_MODEL, page_count)
            embedding_cost = round(max(1, page_count // 3) * 0.00002, 4)
            return {
                "readable": False,
                "suggested_mode": "vision",
                "filename": file.filename,
                "file_type": file_type,
                "file_size_bytes": len(content),
                "page_count": page_count,
                "estimated_knowledge_points": max(1, page_count // 3),
                "estimated_cost": {
                    "extraction": 0.0,
                    "embedding": embedding_cost,
                    "vision": vision_cost,
                    "total": round(vision_cost["total_vision"] + embedding_cost, 4),
                    "currency": "USD",
                    "note": "⚠️ 此文件为图片型 PDF，将使用视觉识别（按页计费，费用较高）",
                },
                "provider": settings.AI_PROVIDER,
                "model": settings.AI_DEFAULT_MODEL or "默认",
            }

    # ── 正常文本路径 ─────────────────────────────
    if not text or not text.strip():
        return {
            "readable": False,
            "suggested_mode": None,
            "filename": file.filename,
            "file_type": file_type,
            "file_size_bytes": len(content),
            "page_count": page_count,
            "estimated_knowledge_points": 0,
            "estimated_cost": {
                "extraction": 0.0,
                "embedding": 0.0,
                "total": 0.0,
                "currency": "USD",
                "note": "无法从文件中提取到文本内容，请确认文件是否损坏",
            },
            "provider": settings.AI_PROVIDER,
            "model": settings.AI_DEFAULT_MODEL or "默认",
        }

    # ── 估算 token 数 ───────────────────────────
    # 中英文混合估算：中文 ~1.5 字符/tok, 英文 ~4 字符/tok, 折中 ~2.8
    estimated_input_tokens = max(1, int(text_len / 2.8))
    # 输出 token 估算：平均每个知识点约 300-500 tokens，
    # 知识点密度约 1 个/1500 输入字符
    estimated_kp_count = max(1, text_len // 1500)
    estimated_output_tokens = estimated_kp_count * 400

    # ── 估算费用 ───────────────────────────────
    cost_estimate = _estimate_cost(
        settings.AI_PROVIDER,
        settings.AI_DEFAULT_MODEL,
        estimated_input_tokens,
        estimated_output_tokens,
    )
    # 嵌入费用：文本分块数 × 每条嵌入费用
    estimated_chunks = max(1, text_len // 2000)
    embedding_cost = round(estimated_chunks * 0.00002, 4)  # DashScope ~$0.02/1M tokens

    return {
        "readable": True,
        "suggested_mode": None,
        "filename": file.filename,
        "file_type": file_type,
        "file_size_bytes": len(content),
        "page_count": page_count,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_total_tokens": estimated_input_tokens + estimated_output_tokens,
        "estimated_knowledge_points": estimated_kp_count,
        "estimated_cost": {
            "extraction": round(cost_estimate, 4),
            "embedding": embedding_cost,
            "total": round(cost_estimate + embedding_cost, 4),
            "currency": "USD",
            "note": "实际费用可能因模型和用量而异，此仅为估算",
        },
        "provider": settings.AI_PROVIDER,
        "model": settings.AI_DEFAULT_MODEL or "默认",
    }


# ── 费用估算辅助 ──────────────────────────────────
# 各模型每 1M token 的参考价格（USD）
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "anthropic": {"input": 3.0, "output": 15.0},
    "openai": {"input": 2.5, "output": 10.0},
    "deepseek": {"input": 0.27, "output": 1.10},
    "qwen": {"input": 0.80, "output": 2.0},
}

# Vision 按页图片费用估算（USD）
_VISION_IMAGE_COST_PER_PAGE: dict[str, float] = {
    "anthropic": 0.0032,
    "openai": 0.0021,
    "qwen": 0.0010,
}


def _estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """根据提供商和 token 数估算费用 (USD)"""
    pricing = _MODEL_PRICING.get(provider, {"input": 1.0, "output": 4.0})
    # 模型级微调（如果配置了特定模型）
    model_lower = (model or "").lower()
    if "flash" in model_lower or "mini" in model_lower:
        pricing = {"input": pricing["input"] * 0.3, "output": pricing["output"] * 0.3}
    elif "opus" in model_lower or "pro" in model_lower:
        pricing = {"input": pricing["input"] * 1.5, "output": pricing["output"] * 1.5}

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def _estimate_vision_cost(provider: str, model: str, page_count: int) -> dict:
    """估算 Vision 管线的费用 (USD)"""
    image_cost = _VISION_IMAGE_COST_PER_PAGE.get(provider, 0.003)
    pricing = _MODEL_PRICING.get(provider, {"input": 1.0, "output": 4.0})
    model_lower = (model or "").lower()
    if "flash" in model_lower or "mini" in model_lower:
        pricing = {"input": pricing["input"] * 0.3, "output": pricing["output"] * 0.3}

    per_page_vision = page_count * (
        image_cost
        + (300 / 1_000_000) * pricing["input"]
        + (500 / 1_000_000) * pricing["output"]
    )
    merge_cost = (
        (page_count * 500 / 1_000_000) * pricing["input"]
        + (1000 / 1_000_000) * pricing["output"]
    )
    return {
        "per_page_extraction": round(per_page_vision, 4),
        "merge_step": round(merge_cost, 4),
        "total_vision": round(per_page_vision + merge_cost, 4),
    }


# ── GET / — 分页列表 ──────────────────────────────
@router.get("/", response_model=CoursewareListResponse)
async def list_coursewares(
    page: int = 1,
    size: int = 20,
    folder_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """获取课件分页列表，按创建时间倒序。可选 folder_id 筛选（传 "null" 表示查根目录）"""
    if page < 1:
        page = 1
    if size < 1:
        size = 1
    if size > 100:
        size = 100

    # 构建查询条件
    conditions = []
    if folder_id is not None:
        if folder_id == "null":
            conditions.append(Courseware.folder_id.is_(None))
        else:
            conditions.append(Courseware.folder_id == folder_id)

    # 查询总数
    count_query = select(func.count(Courseware.id))
    if conditions:
        count_query = count_query.where(*conditions)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    pages = max(1, math.ceil(total / size)) if total > 0 else 0

    # 分页查询
    offset = (page - 1) * size
    query = select(Courseware).order_by(Courseware.created_at.desc())
    if conditions:
        query = query.where(*conditions)
    result = await db.execute(query.offset(offset).limit(size))
    items = list(result.scalars().all())

    return CoursewareListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


# ── GET /{id} — 课件详情 ──────────────────────────
@router.get("/{courseware_id}", response_model=CoursewareResponse)
async def get_courseware(
    courseware_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个课件详情"""
    result = await db.execute(
        select(Courseware).where(Courseware.id == courseware_id)
    )
    courseware = result.scalar_one_or_none()

    if not courseware:
        raise HTTPException(status_code=404, detail="课件不存在")

    return courseware


# ── DELETE /{id} — 删除课件 ───────────────────────
@router.delete("/{courseware_id}", status_code=204)
async def delete_courseware(
    courseware_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除课件（级联删除关联的 chunks、knowledge_points、examples 等）

    同时清理磁盘上的上传文件。
    """
    result = await db.execute(
        select(Courseware).where(Courseware.id == courseware_id)
    )
    courseware = result.scalar_one_or_none()

    if not courseware:
        raise HTTPException(status_code=404, detail="课件不存在")

    # 记录磁盘路径，准备清理
    storage_dir = Path(courseware.file_path).parent if courseware.file_path else None

    # 删除数据库记录（CASCADE 自动清理关联表）
    await db.delete(courseware)
    await db.commit()

    # 清理磁盘文件（先校验路径归属，防止路径遍历攻击）
    if storage_dir and storage_dir.exists():
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        resolved_dir = storage_dir.resolve()
        if not resolved_dir.is_relative_to(upload_root):
            raise HTTPException(
                status_code=500,
                detail="存储目录路径异常，拒绝删除",
            )
        try:
            shutil.rmtree(str(resolved_dir))
        except OSError:
            pass  # 磁盘清理失败不影响响应

    return None

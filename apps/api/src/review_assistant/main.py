"""
FastAPI 应用入口
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from review_assistant.infrastructure.usage.token_counter import BudgetExceededError

from review_assistant.core.config import get_settings
from review_assistant.infrastructure.persistence.database import check_db_connection, dispose_engine

settings = get_settings()
logger = logging.getLogger(__name__)
_recovery_tasks: set[asyncio.Task] = set()


async def recover_incomplete_work() -> None:
    """Resume courseware ingestion and release interrupted homework solves after restart."""
    from sqlalchemy import func, select
    from review_assistant.infrastructure.persistence.database import async_session_factory
    from review_assistant.infrastructure.persistence.models import Courseware, Homework, ChatRequest, KnowledgePoint, Solution
    from review_assistant.application.homework.concurrency import interrupted_homework_status
    from review_assistant.application.ingestion.pipeline import (
        resume_extraction_pipeline,
        run_extraction_pipeline,
    )

    async with async_session_factory() as db:
        interrupted_coursewares = list((await db.execute(
            select(Courseware).where(Courseware.status == "processing")
        )).scalars().all())
        interrupted_homeworks = list((await db.execute(
            select(Homework).where(Homework.status == "processing")
        )).scalars().all())
        interrupted_chat_requests = list((await db.execute(
            select(ChatRequest).where(ChatRequest.status == "processing")
        )).scalars().all())
        recovery_plans: list[tuple[Courseware, str]] = []
        for courseware in interrupted_coursewares:
            if (
                courseware.knowledge_status == "completed"
                and courseware.embedding_status == "processing"
            ):
                recovery_plans.append((courseware, "embedding"))
            elif (
                courseware.embedding_status == "completed"
                and courseware.linking_status in {"pending", "processing"}
            ):
                recovery_plans.append((courseware, "linking"))
            else:
                kp_count = await db.scalar(
                    select(func.count(KnowledgePoint.id)).where(
                        KnowledgePoint.courseware_id == courseware.id
                    )
                ) or 0
                if kp_count == 0:
                    recovery_plans.append((courseware, "restart"))
                else:
                    stage = (
                        "parse" if courseware.parse_status == "processing"
                        else "knowledge"
                    )
                    courseware.status = "partial"
                    courseware.failed_stage = stage
                    courseware.error_message = (
                        "服务重启中断了全量提取；原学习数据已保留，"
                        "如需重提取请明确确认强制操作"
                    )
        for homework in interrupted_homeworks:
            total, answered = (await db.execute(
                select(func.count(Solution.id), func.count(Solution.answer_text)).where(
                    Solution.homework_id == homework.id
                )
            )).one()
            homework.status = interrupted_homework_status(int(total), int(answered))
            homework.error_message = (
                None
                if homework.status == "completed"
                else "服务重启中断了解题；已保存答案保留，可继续未完成题目"
            )
        for chat_request in interrupted_chat_requests:
            chat_request.status = "failed"
            chat_request.error_message = "服务重启中断了生成，可安全重试"
        await db.commit()

    for courseware, plan in recovery_plans:
        if plan in {"embedding", "linking"}:
            coroutine = resume_extraction_pipeline(courseware.id, plan)
        else:
            coroutine = run_extraction_pipeline(
                courseware.id,
                courseware.file_path,
                courseware.file_type,
                re_extract=False,
                use_vision=courseware.use_vision,
            )
        task = asyncio.create_task(coroutine)
        _recovery_tasks.add(task)
        task.add_done_callback(_recovery_tasks.discard)


# ── 生命周期 ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭时的资源管理"""
    # 启动：确保上传目录存在
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "coursewares"), exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "homeworks"), exist_ok=True)

    # 启动 Token 用量监控后台 worker
    from review_assistant.infrastructure.usage.token_counter import start_worker, stop_worker
    await start_worker()
    try:
        await recover_incomplete_work()
    except Exception:
        # 健康检查仍会报告数据库状态；恢复失败不能阻止只读诊断启动。
        logger.exception("启动时恢复未完成任务失败")

    yield

    # 关闭：停止 worker，释放连接池
    from review_assistant.application.chat.jobs import stop_chat_jobs
    from review_assistant.application.homework.jobs import stop_homework_jobs
    await stop_chat_jobs()
    await stop_homework_jobs()
    await stop_worker()
    recovery_tasks = list(_recovery_tasks)
    for task in recovery_tasks:
        task.cancel()
    if recovery_tasks:
        await asyncio.gather(*recovery_tasks, return_exceptions=True)
    await dispose_engine()


# ── 应用实例 ──────────────────────────────────────
app = FastAPI(
    title="期末复习助手 API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


@app.exception_handler(BudgetExceededError)
async def budget_exceeded_handler(request: Request, exc: BudgetExceededError):
    return JSONResponse(status_code=429, content={"detail": str(exc), "code": "AI_BUDGET_EXCEEDED"})

# ── CORS ──────────────────────────────────────────
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 注册路由 ──────────────────────────────────────
from review_assistant.interfaces.http.routes.courses import router as courses_router
app.include_router(courses_router)

from review_assistant.interfaces.http.routes.coursewares import router as coursewares_router
app.include_router(coursewares_router)

from review_assistant.interfaces.http.routes.knowledge_points import courseware_kp_router, kp_router
app.include_router(courseware_kp_router)
app.include_router(kp_router)

from review_assistant.interfaces.http.routes.chat import router as chat_router
app.include_router(chat_router)

from review_assistant.interfaces.http.routes.examples import examples_router
app.include_router(examples_router)

from review_assistant.interfaces.http.routes.homeworks import router as homeworks_router
app.include_router(homeworks_router)

from review_assistant.interfaces.http.routes.links import router as links_router
app.include_router(links_router)

from review_assistant.interfaces.http.routes.admin import router as admin_router
app.include_router(admin_router)

from review_assistant.interfaces.http.routes.folders import router as folders_router
app.include_router(folders_router)

from review_assistant.interfaces.http.routes.questions import router as questions_router
app.include_router(questions_router)

from review_assistant.interfaces.http.routes.progress import router as progress_router
app.include_router(progress_router)


# ── 健康检查 ──────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check(request: Request):
    """健康检查端点"""
    db_ok = await check_db_connection()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status": "ok" if db_ok else "degraded",
            "database": "connected" if db_ok else "disconnected",
            "version": settings.APP_VERSION,
        },
    )

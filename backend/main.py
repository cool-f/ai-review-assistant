"""
FastAPI 应用入口
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.database import check_db_connection, dispose_engine

settings = get_settings()


# ── 生命周期 ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭时的资源管理"""
    # 启动：确保上传目录存在
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "coursewares"), exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "homeworks"), exist_ok=True)

    # 启动 Token 用量监控后台 worker
    from backend.services.token_counter import start_worker, stop_worker
    await start_worker()

    yield

    # 关闭：停止 worker，释放连接池
    await stop_worker()
    await dispose_engine()


# ── 应用实例 ──────────────────────────────────────
app = FastAPI(
    title="期末复习助手 API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

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
from backend.api.coursewares import router as coursewares_router
app.include_router(coursewares_router)

from backend.api.knowledge_points import courseware_kp_router, kp_router
app.include_router(courseware_kp_router)
app.include_router(kp_router)

from backend.api.chat import router as chat_router
app.include_router(chat_router)

from backend.api.examples import examples_router
app.include_router(examples_router)

from backend.api.homeworks import router as homeworks_router
app.include_router(homeworks_router)

from backend.api.links import router as links_router
app.include_router(links_router)

from backend.api.admin import router as admin_router
app.include_router(admin_router)

from backend.api.folders import router as folders_router
app.include_router(folders_router)

from backend.api.questions import router as questions_router
app.include_router(questions_router)

from backend.api.progress import router as progress_router
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

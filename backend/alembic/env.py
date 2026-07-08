"""
Alembic 迁移环境配置
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# 确保 backend 包在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.config import get_settings
from backend.models import Base

# ── Alembic Config 对象 ──────────────────────────────
config = context.config

# ── 日志 ─────────────────────────────────────────────
# Note: skip fileConfig since alembic.ini is not a logging config file

# ── 元数据 ───────────────────────────────────────────
target_metadata = Base.metadata

# ── 运行时 URL ───────────────────────────────────────
settings = get_settings()


def run_migrations_offline() -> None:
    """
    离线模式：生成 SQL 但不连接数据库。
    用法: alembic upgrade head --sql
    """
    context.configure(
        url=settings.DATABASE_URL_SYNC,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式：连接数据库并执行迁移。
    """
    connectable = create_engine(settings.DATABASE_URL_SYNC, echo=settings.DEBUG)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""
配置管理模块
使用 pydantic-settings 从 .env / 环境变量加载配置
"""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    """应用全局配置"""

    model_config = SettingsConfigDict(
        env_file=(_REPOSITORY_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 数据库 ──────────────────────────────────────
    POSTGRES_USER: str = "review_user"
    POSTGRES_PASSWORD: str = "review_pass"
    POSTGRES_DB: str = "review_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Alembic 迁移使用的同步 URL"""
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── 应用 ────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    APP_VERSION: str = "0.2.0"
    CORS_ORIGINS: str = "http://localhost:5173"

    # ── 文件上传 ────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB

    # ── AI 调用 ──────────────────────────────────────
    AI_PROVIDER: str = "openai"
    """AI 提供商: anthropic | openai | qwen | deepseek"""

    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    DASHSCOPE_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""

    AI_DEFAULT_MODEL: str = ""
    """默认模型名称，留空则使用各提供商的默认模型"""
    AI_MAX_TOKENS: int = 4096
    AI_TEMPERATURE: float = 0.7

    # ── Embedding ─────────────────────────────────────
    EMBEDDING_PROVIDER: str = "dashscope"
    """嵌入向量提供商: dashscope"""
    EMBEDDING_MODEL: str = "text-embedding-v4"
    """嵌入模型名称（DashScope text-embedding-v4, 1024 维）"""
    EMBEDDING_DIMENSIONS: int = 1024
    """嵌入向量维度"""
    EMBEDDING_BATCH_SIZE: int = 10
    """嵌入 API 每批最大文本数（DashScope text-embedding-v4 上限为 10）"""

    # ── Token 用量监控 ────────────────────────────
    DAILY_TOKEN_BUDGET: int = 1_000_000
    """每日 Token 用量预算上限，超出后在 API 响应 warning 字段中提示"""

    # ── 知识点关联 ────────────────────────────────────
    LINKING_SIMILARITY_THRESHOLD: float = 0.85
    """知识点关联余弦相似度阈值（0.0 ~ 1.0），高于此值的知识点对视为关联"""


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例"""
    return Settings()

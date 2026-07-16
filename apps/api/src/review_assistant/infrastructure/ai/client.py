"""
AI 调用抽象层

提供:
  - AIMessage        — 统一消息数据类
  - AIResponse       — 统一响应数据类
  - AbstractAIClient — 抽象基类（定义 chat / chat_stream 接口）
  - get_ai_client()  — 工厂函数（根据 AI_PROVIDER 配置返回对应实例）

统一消息格式为 OpenAI 兼容的 messages list:
    [{"role": "system|user|assistant", "content": "..."}]
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator
import math


# ═══════════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AIMessage:
    """统一消息格式 — 与 OpenAI messages 格式兼容"""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        """转换为 dict 格式（用于 API 调用）"""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict) -> "AIMessage":
        """
        从 dict 创建实例

        Args:
            data: 包含 "role" 和可选的 "content" 键的字典

        Returns:
            AIMessage 实例

        Raises:
            ValueError: 当 data 缺少必需的 "role" 键时
        """
        if "role" not in data:
            raise ValueError("AIMessage.from_dict: missing required key 'role'")
        return cls(role=data["role"], content=data.get("content", ""))


@dataclass
class AIResponse:
    """AI 完整响应"""

    content: str
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    })


# ═══════════════════════════════════════════════════════════════════
# 抽象基类
# ═══════════════════════════════════════════════════════════════════

class AbstractAIClient(ABC):
    """
    AI 客户端抽象基类

    所有提供商子类必须实现:
      - chat()        同步（异步）获取完整回复
      - chat_stream() 异步流式逐块返回回复文本

    子类约定:
      - 在 SUPPORTED_MODELS 中声明支持的模型列表
      - 构造函数接收 api_key / model / base_url(可选)
      - API Key 未配置时在 __init__ 中抛出清晰异常
    """

    # 子类必须覆盖此列表
    SUPPORTED_MODELS: list[str] = []

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key:
            raise ValueError(
                f"{self.__class__.__name__}: api_key 不能为空，"
                "请检查对应的环境变量是否已设置"
            )
        if not model:
            raise ValueError(
                f"{self.__class__.__name__}: model 不能为空"
            )
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> AIResponse:
        """
        发送消息并获取完整回复

        Args:
            messages: OpenAI 兼容的消息列表
                [{"role":"system|user|assistant","content":"..."}]
            **kwargs: 提供商特定参数（如 temperature, max_tokens 等）

        Returns:
            AIResponse: 包含 content 和 usage 信息
        """
        ...

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        """Stream incremental response text for an OpenAI-compatible message list."""
        ...


class MeteredAIClient(AbstractAIClient):
    """Budget-enforcing adapter applied once around every text-generation provider."""

    def __init__(self, delegate: AbstractAIClient):
        self.delegate = delegate
        self.api_key = delegate.api_key
        self.model = delegate.model
        self.base_url = delegate.base_url

    async def chat(self, messages: list[dict], **kwargs) -> AIResponse:
        from review_assistant.infrastructure.usage.token_counter import ensure_budget, record_usage
        from review_assistant.infrastructure.usage.context import current_usage_context

        await ensure_budget()
        response = await self.delegate.chat(messages, **kwargs)
        prompt = int(response.usage.get("prompt_tokens") or _estimate_message_tokens(messages))
        completion = int(response.usage.get("completion_tokens") or _estimate_tokens(response.content))
        context = current_usage_context()
        await record_usage(
            provider=_provider_name(self.delegate), model=self.model,
            prompt_tokens=prompt, completion_tokens=completion,
            session_id=context.session_id, course_id=context.course_id, purpose=context.purpose,
        )
        return response

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        from review_assistant.infrastructure.usage.token_counter import ensure_budget, record_usage
        from review_assistant.infrastructure.usage.context import current_usage_context

        await ensure_budget()
        chunks: list[str] = []
        try:
            async for chunk in self.delegate.chat_stream(messages, **kwargs):
                chunks.append(chunk)
                yield chunk
        finally:
            context = current_usage_context()
            await record_usage(
                provider=_provider_name(self.delegate), model=self.model,
                prompt_tokens=_estimate_message_tokens(messages),
                completion_tokens=_estimate_tokens("".join(chunks)) if chunks else 0,
                session_id=context.session_id, course_id=context.course_id, purpose=context.purpose,
            )


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 3.5)) if text else 0


def _estimate_message_tokens(messages: list[dict]) -> int:
    return sum(_estimate_tokens(str(message.get("content", ""))) for message in messages)


def _provider_name(client: AbstractAIClient) -> str:
    name = client.__class__.__name__.lower()
    for provider in ("anthropic", "openai", "qwen", "deepseek"):
        if provider in name:
            return provider
    return "unknown"

# ═══════════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════════

def get_ai_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AbstractAIClient:
    """
    工厂函数：根据 AI_PROVIDER 配置或 model 名称自动推断返回对应的 AI 客户端实例

    参数优先级: 函数参数 > 环境变量 / Settings > 默认值

    当未显式指定 provider 时，按以下顺序自动检测:
      1. 从 model 名称前缀推断 (如 "claude-" → anthropic, "gpt-" → openai)
      2. 从 Settings.AI_PROVIDER 读取
      3. 依次检查各提供商的 API Key 环境变量，使用第一个已配置的

    Args:
        provider: 提供商标识 (anthropic | openai | qwen | deepseek)，可选
        api_key: API 密钥，默认从配置读取
        model:    模型名称，默认从配置或提供商默认模型
        base_url: 自定义 API 端点，默认使用提供商官方端点

    Returns:
        AbstractAIClient 的具体子类实例

    Raises:
        ValueError: 提供商不支持或 API Key 未配置
    """
    from review_assistant.core.config import get_settings

    settings = get_settings()

    # ── 确定 provider ────────────────────────────────
    # 优先级: 函数参数 > model 推断 > Settings.AI_PROVIDER > 环境变量探测
    resolved_provider = provider or _detect_provider(
        model or settings.AI_DEFAULT_MODEL, settings
    )

    # ── Anthropic ──────────────────────────────────────
    if resolved_provider == "anthropic":
        from review_assistant.infrastructure.ai.providers.anthropic import AnthropicClient

        api_key = api_key or settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY 未配置，请在 .env 文件中设置 ANTHROPIC_API_KEY"
            )
        model = model or settings.AI_DEFAULT_MODEL or "claude-sonnet-4-20250514"
        return MeteredAIClient(AnthropicClient(api_key=api_key, model=model, base_url=base_url))

    # ── OpenAI ─────────────────────────────────────────
    elif resolved_provider == "openai":
        from review_assistant.infrastructure.ai.providers.openai import OpenAIClient

        api_key = api_key or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY 未配置，请在 .env 文件中设置 OPENAI_API_KEY"
            )
        model = model or settings.AI_DEFAULT_MODEL or "gpt-4o"
        return MeteredAIClient(OpenAIClient(api_key=api_key, model=model, base_url=base_url))

    # ── 通义千问 (DashScope) ────────────────────────
    elif resolved_provider == "qwen":
        from review_assistant.infrastructure.ai.providers.qwen import QwenClient

        api_key = api_key or settings.DASHSCOPE_API_KEY
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY 未配置，请在 .env 文件中设置 DASHSCOPE_API_KEY"
            )
        model = model or settings.AI_DEFAULT_MODEL or "qwen-plus"
        return MeteredAIClient(QwenClient(api_key=api_key, model=model, base_url=base_url))

    # ── DeepSeek ──────────────────────────────────────
    elif resolved_provider == "deepseek":
        from review_assistant.infrastructure.ai.providers.deepseek import DeepSeekClient

        api_key = api_key or settings.DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 未配置，请在 .env 文件中设置 DEEPSEEK_API_KEY"
            )
        model = model or settings.AI_DEFAULT_MODEL or "deepseek-chat"
        return MeteredAIClient(DeepSeekClient(api_key=api_key, model=model, base_url=base_url))

    # ── 不支持 ─────────────────────────────────────────
    else:
        raise ValueError(
            f"不支持的 AI provider: '{resolved_provider}'，"
            f"可选值: anthropic, openai, qwen, deepseek。"
            f"请在 .env 中设置 AI_PROVIDER 或确保 AI_DEFAULT_MODEL "
            f"使用可识别的模型名前缀 (如 claude-/gpt-/qwen-/deepseek-)"
        )


# ── Provider 自动检测 ──────────────────────────────
# 模型名前缀 → provider 映射
_MODEL_PREFIX_MAP: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("qwen", "qwen"),
    ("deepseek", "deepseek"),
]


def _detect_provider(model: str, settings) -> str:
    """
    从 model 名称自动推断 provider

    检测顺序:
      1. model 名称前缀匹配 _MODEL_PREFIX_MAP
      2. Settings.AI_PROVIDER（如果显式配置了非空值）
      3. 环境变量探测（检查哪个 API Key 已配置）

    Returns:
        提供商标识字符串

    Raises:
        ValueError: 无法自动检测且无有效的 API Key
    """
    import logging
    _logger = logging.getLogger(__name__)

    # ── 1. 从 model 名称推断 ─────────────────────────
    if model:
        model_lower = model.lower()
        for prefix, provider in _MODEL_PREFIX_MAP:
            if model_lower.startswith(prefix):
                _logger.info("自动检测到 provider: %s (from model=%s)", provider, model)
                return provider

    # ── 2. 从 Settings.AI_PROVIDER 读取 ──────────────
    if settings.AI_PROVIDER:
        return settings.AI_PROVIDER

    # ── 3. 环境变量探测（依次检查）────────────────
    env_checks: list[tuple[str, str]] = [
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("DASHSCOPE_API_KEY", "qwen"),
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
    ]
    for env_var, provider in env_checks:
        key = getattr(settings, env_var, "")
        if key:
            _logger.info(
                "自动检测到 provider: %s (from %s in .env)", provider, env_var
            )
            return provider

    raise ValueError(
        "无法自动检测 AI provider。请执行以下任一操作:\n"
        "  1. 在 .env 中设置 AI_PROVIDER (anthropic/openai/qwen/deepseek)\n"
        "  2. 设置 AI_DEFAULT_MODEL 为可识别的模型名 (如 gpt-4o, claude-sonnet-4, "
        "deepseek-chat, qwen-plus)\n"
        "  3. 设置至少一个 API Key 环境变量 (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
        "DASHSCOPE_API_KEY / DEEPSEEK_API_KEY)"
    )

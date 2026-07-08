"""
OpenAI (GPT) 提供商

使用 openai SDK 调用 GPT 系列模型。
消息格式本身就是 OpenAI 原生格式，无需转换。
"""

from backend.services.providers._openai_compatible import OpenAICompatibleClient


class OpenAIClient(OpenAICompatibleClient):
    """OpenAI GPT 客户端"""

    SUPPORTED_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o1",
        "o1-mini",
    ]

    # OpenAI 官方 API 使用 openai SDK 内置默认端点，
    # 因此 DEFAULT_BASE_URL 保持为基类的 None

"""
DeepSeek 提供商

通过 DeepSeek 的 OpenAI 兼容接口调用 DeepSeek 模型。

DeepSeek OpenAI 兼容端点:
    https://api.deepseek.com

API Key 获取: https://platform.deepseek.com/api_keys
"""

from backend.services.providers._openai_compatible import OpenAICompatibleClient


class DeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 客户端（OpenAI 兼容模式）"""

    DEFAULT_BASE_URL = "https://api.deepseek.com"

    SUPPORTED_MODELS = [
        "deepseek-chat",
        "deepseek-reasoner",
    ]

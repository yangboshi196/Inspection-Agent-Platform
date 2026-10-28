"""
SIA_agent.llm.impl - LLM 模型实现层

两层实现架构：
- http_api：通用 HTTP API 模型实现（chat / embedding / visual / voice 四种用途）
- openai_compat：OpenAI 兼容接口模型实现

各实现均继承自 `llm/base.py` 中对应的抽象基类（ChatModel / EmbeddingModel / VisualModel / VoiceModel），
由 ModelManager 统一调度，调用方无需感知底层实现差异。
"""

from .http_api import HttpApiChatModel, HttpApiEmbeddingModel, HttpApiVisualModel
from .http_api import HttpApiVoiceModel
from .openai_compat import OpenAICompatVoiceModel

__all__ = [
    "HttpApiChatModel",
    "HttpApiEmbeddingModel",
    "HttpApiVisualModel",
    "HttpApiVoiceModel",
    "OpenAICompatVoiceModel",
]


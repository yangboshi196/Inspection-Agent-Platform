"""平台 LLM / OpenAI 兼容 API 封装。"""

from inspection_platform.llm.async_runtime import get_thread_pool, run_async, submit_async
from inspection_platform.llm.chat import call_chat, call_chat_async
from inspection_platform.llm.openai_client import (
    get_async_openai_client,
    is_openai_api_configured,
    openai_api_key,
    openai_base_url,
    openai_chat_model,
    openai_embed_model,
)

__all__ = [
    "call_chat",
    "call_chat_async",
    "get_async_openai_client",
    "get_thread_pool",
    "is_openai_api_configured",
    "openai_api_key",
    "openai_base_url",
    "openai_chat_model",
    "openai_embed_model",
    "run_async",
    "submit_async",
]

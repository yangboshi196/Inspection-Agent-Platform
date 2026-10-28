"""LLM 模块 - 多模型抽象层统一出口

定义四类模型抽象基类（Chat/Embedding/Visual/Voice），
以及 LLM 层统一异常（LLMError）。

实现层：
- impl/http_api     : 项目自定义 HTTP 对话后端（SiliconFlow 等）
- impl/openai_compat: OpenAI/vLLM 兼容协议实现

类型定义（types.py）：
- LlmChatMessage / ChatRequest / ChatResponse : 对话接口
- EmbeddingRequest / EmbeddingResponse        : 向量接口
- VisualRequest / VisualResponse              : 多模态接口
- VoiceRequest / VoiceResponse                : 语音接口

Usage:
    from SIA_agent.llm import ChatModel, LLMError, ChatRequest

    # 调用模型
    resp = model.call(ChatRequest(messages=[...], metadata={}))
"""

from .base import AbstractLLM, ChatModel, EmbeddingModel, ModelCapabilities, VisualModel, VoiceModel
from .errors import LLMError
from .types import (
    AudioInput,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ImageInput,
    LlmChatMessage,
    Message,
    ToolCall,
    VisualImage,
    VisualRequest,
    VisualResponse,
    VoiceRequest,
    VoiceResponse,
    to_llm_chat_message,
)

__all__ = [
    "AbstractLLM",
    "ChatModel",
    "EmbeddingModel",
    "VisualModel",
    "VoiceModel",
    "ModelCapabilities",
    "LLMError",
    "LlmChatMessage",
    "Message",
    "ChatRequest",
    "ChatResponse",
    "ToolCall",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "ImageInput",
    "VisualImage",
    "VisualRequest",
    "VisualResponse",
    "AudioInput",
    "VoiceRequest",
    "VoiceResponse",
    "to_llm_chat_message",
]


"""LLM 模块 - 请求/响应类型定义

定义 LLM 接口层所需的全部数据结构（Request/Response）：

对话接口：
- LlmChatMessage / ChatRequest / ChatResponse
- ToolCall        : 工具调用结构

向量接口：
- EmbeddingRequest / EmbeddingResponse

多模态接口：
- VisualImage / VisualRequest / VisualResponse
- ImageInput       : 业务侧图片输入

语音接口：
- AudioInput / VoiceRequest / VoiceResponse

类型别名：
- Role  : 消息角色（system/user/assistant/tool）
- to_llm_chat_message() : 从业务层 Message 转换为 LLM 层消息
- Message（向后兼容别名）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

# 统一 Message 定义，引用业务层
if TYPE_CHECKING:
    from ..context.models import Message as BusinessMessage

Role = Literal["system", "user", "assistant", "tool"]


def to_llm_chat_message(msg: "BusinessMessage") -> "LlmChatMessage":
    """从业务层 Message 提取 LLM 层所需字段。

    仅复制 role/content/metadata，不携带 session_id 等业务层信息。

    Args:
        msg: 来自 context.models.Message 的业务层消息。

    Returns:
        LlmChatMessage: 可直接传入 ChatRequest 的 LLM 层消息。
    """
    return LlmChatMessage(role=msg.role, content=msg.content, metadata=msg.metadata)


@dataclass(frozen=True)
class LlmChatMessage:
    """LLM 接口层消息结构（不可变）。

    仅包含模型调用所需的最小字段。通过 `to_llm_chat_message()`
    从业务层 Message 转换得到。

    Attributes:
        role: 消息角色（system/user/assistant/tool）。
        content: 消息正文。
        metadata: 扩展元数据（如 tool_calls、kind 等）。
    """
    role: Role
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# 向后兼容别名（建议优先使用 LlmChatMessage）
Message = LlmChatMessage

# 向后兼容别名
to_llm_message = to_llm_chat_message


@dataclass(frozen=True)
class ChatRequest:
    messages: list[Message]
    metadata: dict[str, Any]
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    raw: Any | None = None


@dataclass(frozen=True)
class EmbeddingRequest:
    texts: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    dimension: int
    usage: dict[str, Any] | None = None
    raw: Any | None = None


@dataclass(frozen=True)
class VisualImage:
    uri: str | None = None
    base64: str | None = None
    """当仅提供 base64 时，用于组装 data URL 的 mime（如 image/jpeg）；缺省则由网关侧猜测。"""
    mime_type: str | None = None


@dataclass(frozen=True)
class ImageInput:
    """
    业务侧图片输入（标准化为 `VisualImage` 之前）：URI 或 base64 二选一为主。
    与 `VisualImage` 字段对齐，供 `normalize_image_input` 等工具链使用。
    """

    uri: str | None = None
    base64: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class VisualRequest:
    prompt: str
    images: list[VisualImage] | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VisualResponse:
    content: str
    images: list[VisualImage] | None = None
    usage: dict[str, Any] | None = None
    raw: Any | None = None


@dataclass(frozen=True)
class AudioInput:
    """
    语音输入：支持 URI 或 base64（二选一）。
    - uri：如 http(s)://、file:// 或对象存储地址
    - base64：不建议长期存储；建议业务侧落到对象存储再传 uri
    """

    uri: str | None = None
    base64: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class VoiceRequest:
    """
    语音识别（ASR）请求。
    最小字段：audio + metadata（带 request_id）
    """

    audio: AudioInput
    metadata: dict[str, Any]
    language: str | None = None
    prompt: str | None = None


@dataclass(frozen=True)
class VoiceResponse:
    """
    语音识别（ASR）响应（最小可用）。
    """

    text: str
    segments: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    raw: Any | None = None


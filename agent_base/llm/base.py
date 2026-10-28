"""LLM 模块 - 模型能力抽象与接口定义

本模块定义四类模型抽象基类及能力描述：
- AbstractLLM   : 公共基类（端点/API Key/ping/health）
- ChatModel     : 对话模型
- EmbeddingModel: 向量模型
- VisualModel   : 视觉/多模态模型
- VoiceModel    : 语音模型
- ModelCapabilities: 能力开关（流式/工具调用/多模态等）

具体实现见 impl/http_api.py 和 impl/openai_compat.py。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from .types import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    VisualRequest,
    VisualResponse,
    VoiceRequest,
    VoiceResponse,
)


@dataclass(frozen=True)
class ModelCapabilities:
    """描述某类模型在协议层支持的能力开关。

    Attributes:
        stream: 是否支持流式输出。
        tool_call: 是否支持函数调用（Function Calling）。
        json_schema: 是否支持 JSON Schema 输出。
        max_input_tokens: 最大输入 token 数。
        max_output_tokens: 最大输出 token 数。
        dimension: 向量维度（Embedding 模型）。
        max_batch: 最大批量大小。
        image_input: 是否支持图片输入。
        image_max_size: 图片最大尺寸（字节）。
    """

    stream: bool = False
    tool_call: bool = False
    json_schema: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    dimension: int | None = None
    max_batch: int | None = None
    image_input: bool | None = None
    image_max_size: int | None = None


class AbstractLLM(abc.ABC):
    """LLM 客户端公共基类：持有端点信息与可选 API Key，子类实现 `call` / `ping`。

    Attributes:
        model_name: 模型名称（如 qwen-max）。
        source: 来源类型（local/api）。
        url: 服务端点地址。
        api_key: 当前使用的 API Key（可能为 None）。
        capabilities: 该模型的能力描述。
        tags: 标签列表（如 ["default", "backup"]）。
        provider: 提供商名称。
    """

    def __init__(
        self,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        capabilities: ModelCapabilities | None = None,
        tags: list[str] | None = None,
        provider: str | None = None,
    ) -> None:
        """初始化 LLM 客户端实例。

        Args:
            model_name: 模型名称标识，如 "qwen-max"、"gpt-4o" 等。
            source: 来源类型，用于标识是本地部署还是第三方 API（"local" / "api"）。
            url: 服务端点地址，API 调用将发送到此 URL。
            api_key: 可选的 API Key，如果为 None 则表示本地服务无需鉴权。
            capabilities: 模型能力描述，如果不提供则使用默认能力集。
            tags: 标签列表，可用于模型分组（如 ["default", "backup"]）。
            provider: 提供商名称，默认为 source 值。

        Returns:
            None
        """
        self.model_name = model_name
        self.source = source
        self.url = url
        self._api_key = api_key
        self.capabilities = capabilities or ModelCapabilities()
        self.tags = tags or []
        self.provider = provider or source

    @property
    def api_key(self) -> str | None:
        """当前请求使用的 API Key（可能为 `None`，例如本地服务）。"""
        return self._api_key

    def set_api_key(self, api_key: str | None) -> None:
        """运行时覆盖 API Key（一般无需调用，密钥多由 `ModelManager` 注入）。"""
        self._api_key = api_key

    @abc.abstractmethod
    def call(self, request: Any) -> Any:
        """执行一次同步推理；`request` 类型由子类约定。"""
        raise NotImplementedError

    def stream_call(self, request: Any):
        """流式输出（未实现或非流式模型时抛出 `NotImplementedError`）。"""
        if not self.capabilities.stream:
            raise NotImplementedError("stream_call not supported by this model")
        raise NotImplementedError

    @abc.abstractmethod
    def ping(self, timeout_ms: int = 1000) -> bool:
        """轻量探活（如请求模型列表）；超时或网络错误返回 `False`。"""
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        """返回最小健康信息字典（不含密钥）。"""
        return {"model_name": self.model_name, "provider": self.provider}


class ChatModel(AbstractLLM):
    """对话模型抽象：输入 `ChatRequest`，输出 `ChatResponse`。"""

    @abc.abstractmethod
    def call(self, request: ChatRequest) -> ChatResponse:  # type: ignore[override]
        raise NotImplementedError


class EmbeddingModel(AbstractLLM):
    """向量模型抽象：输入 `EmbeddingRequest`，输出 `EmbeddingResponse`。"""

    @abc.abstractmethod
    def call(self, request: EmbeddingRequest) -> EmbeddingResponse:  # type: ignore[override]
        raise NotImplementedError


class VisualModel(AbstractLLM):
    """视觉/多模态模型抽象：输入 `VisualRequest`，输出 `VisualResponse`。"""

    @abc.abstractmethod
    def call(self, request: VisualRequest) -> VisualResponse:  # type: ignore[override]
        raise NotImplementedError


class VoiceModel(AbstractLLM):
    """语音模型抽象（如 ASR）：输入 `VoiceRequest`，输出 `VoiceResponse`。"""

    @abc.abstractmethod
    def call(self, request: VoiceRequest) -> VoiceResponse:  # type: ignore[override]
        raise NotImplementedError


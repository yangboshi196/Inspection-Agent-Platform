"""
SIA_agent.llm.impl.http_api - 通用 HTTP API 模型实现

适用于任意遵循以下规范的 LLM API：
- Chat Completions（POST JSON，Streaming Server-Sent Events）
- Embedding（POST JSON，返回向量列表）
- Visual（多模态图像/视频理解，POST multipart 或 JSON）
- Voice（语音识别，POST audio blob）

重试策略：
- max_retries：最大重试次数（默认 1，不含首次）
- retry_backoff_ms：重试间隔基础值（默认 200ms，按指数退避）

超时控制：
- connect_timeout_ms：连接建立超时
- timeout_ms：请求总超时（含读取）
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..base import ChatModel, EmbeddingModel, ModelCapabilities, VisualModel, VoiceModel
from ..errors import LLMError, redact_secrets
from ..types import (
    AudioInput,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ToolCall,
    VisualRequest,
    VisualResponse,
    VoiceRequest,
    VoiceResponse,
)


def _classify_http_error(status_code: int) -> tuple[str, bool]:
    """将 HTTP 状态码映射为 `LLMError` 使用的 `(code, retryable)`。

    401/403 鉴权失败；429 限流；5xx 服务端错误；其余按不可重试的坏请求处理。
    """
    if status_code in (401, 403):
        return "AUTH_FAILED", False
    if status_code == 429:
        return "RATE_LIMITED", True
    if 500 <= status_code <= 599:
        return "MODEL_UNAVAILABLE", True
    return "BAD_REQUEST", False


def _client_timeout(*, connect_timeout_ms: int, timeout_ms: int) -> httpx.Timeout:
    """按毫秒构造 `httpx.Timeout`：建连单独计时，读写与 pool 使用同一上限。"""
    # connect：建连超时；read/write/pool：整体请求读写超时（最小实现）
    connect_s = max(0.001, float(connect_timeout_ms) / 1000.0)
    read_s = max(0.001, float(timeout_ms) / 1000.0)
    return httpx.Timeout(connect=connect_s, read=read_s, write=read_s, pool=connect_s)


class HttpApiChatModel(ChatModel):
    """项目自定义的 HTTP 对话后端。

    将 `ChatRequest` 的字段 JSON 化后 `POST {url}/chat`，期望响应体可直接映射
    为 `ChatResponse` 所需字段。
    """

    def __init__(
        self,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """保存网关地址、可选 Bearer 密钥以及单次请求的 HTTP 超时配置。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=url.rstrip("/"),
            api_key=api_key,
            capabilities=ModelCapabilities(tool_call=True),
            tags=tags,
            provider=provider,
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: ChatRequest) -> ChatResponse:  # type: ignore[override]
        """调用 `{url}/chat` 完成一轮对话并返回结构化结果。

        请求体包含完整 messages 与 tools 等；成功时从 JSON 取 `content`、
        `tool_calls`、`usage` 等；HTTP/网络错误转为 `LLMError`。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content, "metadata": m.metadata} for m in request.messages],
            "metadata": request.metadata,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_output_tokens": request.max_output_tokens,
            "tools": request.tools,
            "tool_choice": request.tool_choice,
        }

        t0 = time.perf_counter()
        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/chat", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError(
                code="TIMEOUT",
                message="http timeout",
                retryable=True,
                provider=self.provider,
                request_id=request_id,
                raw={"error": str(e)},
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(
                code="NETWORK_ERROR",
                message="http network error",
                retryable=True,
                provider=self.provider,
                request_id=request_id,
                raw={"error": str(e)},
            ) from e

        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            code, retryable = _classify_http_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(
                code=code,  # type: ignore[arg-type]
                message=f"http {resp.status_code}: {msg}",
                retryable=retryable,
                provider=self.provider,
                request_id=request_id,
                raw={"status_code": resp.status_code, "latency_ms": latency_ms},
            )

        data = resp.json()
        tool_calls = None
        if data.get("tool_calls"):
            tool_calls = [
                ToolCall(id=str(c.get("id", "")), name=str(c["name"]), arguments=dict(c.get("arguments") or {}))
                for c in data["tool_calls"]
            ]
        return ChatResponse(
            content=str(data.get("content", "")),
            tool_calls=tool_calls,
            usage=data.get("usage"),
            finish_reason=data.get("finish_reason"),
            raw=data,
        )

    def ping(self, timeout_ms: int = 1000) -> bool:
        """请求 `{url}/health` 做存活探测；状态码小于 400 视为可用。"""
        try:
            timeout = _client_timeout(connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms), timeout_ms=timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/health")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class HttpApiEmbeddingModel(EmbeddingModel):
    """自定义 HTTP 向量服务：`POST {url}/embedding`。"""

    def __init__(
        self,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """保存向量服务端点、可选鉴权与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=url.rstrip("/"),
            api_key=api_key,
            capabilities=ModelCapabilities(),
            tags=tags,
            provider=provider,
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: EmbeddingRequest) -> EmbeddingResponse:  # type: ignore[override]
        """批量提交文本，从 JSON 中取 `vectors` 与 `dimension` 构造响应。"""
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {"model": self.model_name, "texts": request.texts, "metadata": request.metadata}
        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/embedding", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e

        if resp.status_code >= 400:
            code, retryable = _classify_http_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        data = resp.json()
        vectors = data.get("vectors") or []
        dimension = int(data.get("dimension") or (len(vectors[0]) if vectors else 0))
        return EmbeddingResponse(vectors=vectors, dimension=dimension, usage=data.get("usage"), raw=data)

    def ping(self, timeout_ms: int = 1000) -> bool:
        """GET `{url}/health` 判断服务是否在线。"""
        try:
            timeout = _client_timeout(connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms), timeout_ms=timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/health")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class HttpApiVisualModel(VisualModel):
    """自定义 HTTP 多模态/视觉：`POST {url}/visual`。"""

    def __init__(
        self,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """保存视觉服务端点、可选鉴权与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=url.rstrip("/"),
            api_key=api_key,
            capabilities=ModelCapabilities(),
            tags=tags,
            provider=provider,
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: VisualRequest) -> VisualResponse:  # type: ignore[override]
        """将 prompt 与 images 序列化后调用 `{url}/visual`，解析文本结果。"""
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": request.prompt,
            "images": [i.__dict__ for i in (request.images or [])],
            "metadata": request.metadata,
        }
        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/visual", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e

        if resp.status_code >= 400:
            code, retryable = _classify_http_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        data = resp.json()
        return VisualResponse(content=str(data.get("content", "")), usage=data.get("usage"), raw=data)

    def ping(self, timeout_ms: int = 1000) -> bool:
        """GET `{url}/health` 判断服务是否在线。"""
        try:
            timeout = _client_timeout(connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms), timeout_ms=timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/health")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class HttpApiVoiceModel(VoiceModel):
    """自定义 HTTP 语音识别：`POST {url}/voice`（JSON 携带音频描述）。"""

    def __init__(
        self,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """保存语音服务端点、可选鉴权与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=url.rstrip("/"),
            api_key=api_key,
            capabilities=ModelCapabilities(),
            tags=tags,
            provider=provider,
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: VoiceRequest) -> VoiceResponse:  # type: ignore[override]
        """将音频 URI/base64 等元数据 JSON 化后调用 `{url}/voice`，组装转写结果。"""
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        audio: AudioInput = request.audio
        payload: dict[str, Any] = {
            "model": self.model_name,
            "audio": {"uri": audio.uri, "base64": audio.base64, "mime_type": audio.mime_type},
            "language": request.language,
            "prompt": request.prompt,
            "metadata": request.metadata,
        }

        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/voice", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e

        if resp.status_code >= 400:
            code, retryable = _classify_http_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        data = resp.json()
        return VoiceResponse(
            text=str(data.get("text", "")),
            segments=data.get("segments"),
            usage=data.get("usage"),
            raw=data,
        )

    def ping(self, timeout_ms: int = 1000) -> bool:
        """GET `{url}/health` 判断服务是否在线。"""
        try:
            timeout = _client_timeout(connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms), timeout_ms=timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/health")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


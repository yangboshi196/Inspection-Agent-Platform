"""
SIA_agent.llm.impl.openai_compat - OpenAI 兼容接口模型实现

适用于提供 OpenAI 兼容 API 端点的 LLM 服务（如 SiliconFlow、VLLM、Ollama 等）。
支持 chat / embedding / visual / voice 四种用途。

与 http_api 的区别：
- http_api：适用于通用 HTTP API（自研接口或特殊协议）
- openai_compat：严格遵循 OpenAI Chat Completions / Embeddings / Audio API 格式

特殊处理：
- 图片输入：支持 base64 本地图片（自动转换为 data URL）
- 工具调用：支持 OpenAI function calling 格式的 tool_calls
- 流式：严格遵循 SSE 格式，逐块 yield delta
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from ..base import ChatModel, EmbeddingModel, ModelCapabilities, VisualModel, VoiceModel
from ..errors import LLMError, redact_secrets
from ..mime import guess_image_mime_from_bytes
from ..types import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    Message,
    ToolCall,
    VisualImage,
    VisualRequest,
    VisualResponse,
    AudioInput,
    VoiceRequest,
    VoiceResponse,
)


def _normalize_openai_api_root(url: str) -> str:
    """本实现请求路径为 ``{root}/v1/chat/completions``；``.env`` 常为 ``.../v1``。"""
    u = (url or "").strip().rstrip("/")
    if u.endswith("/v1"):
        return u[:-3]
    return u


def _map_status_to_llm_error(status_code: int) -> tuple[str, bool]:
    """将 HTTP 状态码映射为 `LLMError` 使用的 `(code, retryable)`。

    401/403 视为鉴权失败不可重试；429 限流与 5xx 服务端错误可重试；其余 4xx
    归为不可重试的坏请求。
    """
    if status_code in (401, 403):
        return "AUTH_FAILED", False
    if status_code == 429:
        return "RATE_LIMITED", True
    if 500 <= status_code <= 599:
        return "MODEL_UNAVAILABLE", True
    return "BAD_REQUEST", False


def _message_to_openai(m: Message, *, provider: str | None = None) -> dict[str, Any]:
    """单条 `Message` → OpenAI Chat `messages` 元素（含工具多轮所需字段）。

    注意：不同网关对 `messages` 的限制不一；这里做最小字段输出，并对少数 provider 做兼容。
    """
    meta = dict(m.metadata or {})
    if m.role == "assistant":
        tcalls = meta.get("tool_calls")
        if isinstance(tcalls, list) and tcalls:
            # 兼容更严格的网关：不要发送 content:null（部分实现会直接判 messages illegal）
            body: dict[str, Any] = {"role": "assistant", "tool_calls": tcalls}
            c = (m.content or "").strip()
            if c:
                body["content"] = c
            return body
        return {"role": "assistant", "content": str(m.content or "")}
    if m.role == "tool":
        # 部分 OpenAI 兼容网关（如 siliconflow）不接受 role=tool，需把工具结果“内联”为普通文本消息
        if (provider or "").lower() == "siliconflow":
            tname = str(meta.get("tool_name") or meta.get("name") or "tool")
            tcid = str(meta.get("tool_call_id") or "")
            prefix = f"[tool:{tname}]"
            if tcid:
                prefix = f"{prefix}[{tcid}]"
            content = str(m.content or "")
            return {"role": "assistant", "content": f"{prefix}\n{content}".strip()}

        # OpenAI 标准 tool message：仅需要 tool_call_id + content；name 在部分实现里会触发非法字段
        body: dict[str, Any] = {"role": "tool", "content": str(m.content or "")}
        tcid = meta.get("tool_call_id")
        if tcid:
            body["tool_call_id"] = str(tcid)
        return body
    return {"role": m.role, "content": str(m.content or "")}


def _to_openai_messages(messages: list[Message], *, provider: str | None = None) -> list[dict[str, Any]]:
    """把内部 `Message` 列表序列化为 OpenAI Chat 所需的 `messages`。"""
    return [_message_to_openai(m, provider=provider) for m in messages]


def _client_timeout(*, connect_timeout_ms: int, timeout_ms: int) -> httpx.Timeout:
    """按毫秒构造 `httpx.Timeout`，区分建连与单次请求读写等待。

    建连使用 `connect_timeout_ms`；读、写与 pool 使用 `timeout_ms`，与「一次
    HTTP 往返」的整体超时语义对齐。
    """
    # httpx.Timeout: connect + read/write/pool 分开；这里把“整体超时”映射到 read 超时
    connect_s = max(0.001, float(connect_timeout_ms) / 1000.0)
    read_s = max(0.001, float(timeout_ms) / 1000.0)
    return httpx.Timeout(connect=connect_s, read=read_s, write=read_s, pool=read_s)


class OpenAICompatChatModel(ChatModel):
    """OpenAI 兼容的文本对话模型（vLLM、各类网关常见）。

    在 `url` 表示的服务根路径下调用 `POST /v1/chat/completions`，请求与响应
    字段遵循 OpenAI Chat Completions 约定。
    """

    def __init__(
        self,
        *,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """初始化模型元数据、服务根地址与 HTTP 行为参数。

        `url` 为不含 `/v1` 的根地址；若提供 `api_key` 则在请求头附带 Bearer
        令牌。`timeout_ms` / `connect_timeout_ms` 分别约束读写与建连。
        """
        super().__init__(
            model_name=model_name,
            source=source,
            url=_normalize_openai_api_root(url),
            api_key=api_key,
            capabilities=ModelCapabilities(tool_call=True, stream=True),
            tags=tags,
            provider=provider or "openai_compat",
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: ChatRequest) -> ChatResponse:  # type: ignore[override]
        """执行一次聊天补全，返回 `ChatResponse`。

        将消息、temperature、max_tokens、tools 等序列化为 JSON 后 POST 到
        `/v1/chat/completions`；成功时从 `choices[0].message` 取正文与
        `tool_calls`（函数字符串参数尽量 JSON 解析，失败则包在 `_raw`）。
        超时、网络错误与 HTTP 错误统一转换为 `LLMError`。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _to_openai_messages(request.messages, provider=self.provider),
        }
        msg_shapes = [{"role": m.get("role"), "keys": sorted(list(m.keys()))} for m in payload["messages"]]
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_output_tokens is not None:
            # OpenAI 兼容字段名
            payload["max_tokens"] = request.max_output_tokens

        # tools（可选）：真实业务可逐步补齐 schema/tool_choice
        if request.tools is not None:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice

        t0 = time.perf_counter()
        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/v1/chat/completions", json=payload, headers=headers)
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
            code, retryable = _map_status_to_llm_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            diag = ""
            if resp.status_code == 400:
                diag = f" message_shapes={msg_shapes}"
            raise LLMError(
                code=code,  # type: ignore[arg-type]
                message=f"http {resp.status_code}: {msg}{diag}",
                retryable=retryable,
                provider=self.provider,
                request_id=request_id,
                raw={"status_code": resp.status_code, "latency_ms": latency_ms, "message_shapes": msg_shapes},
            )

        data = resp.json()
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = msg.get("content") or ""

        tool_calls = None
        # OpenAI 工具调用格式：message.tool_calls
        if msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                # arguments 通常是 JSON string；这里做最小兼容：能解析就解析，不能就原样包一层
                args_raw = fn.get("arguments")
                args: dict[str, Any]
                if isinstance(args_raw, str):
                    try:
                        import json as _json

                        args = _json.loads(args_raw) if args_raw.strip() else {}
                    except Exception:
                        args = {"_raw": args_raw}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=str(tc.get("id") or ""),
                        name=str(fn.get("name") or ""),
                        arguments=args,
                    )
                )

        return ChatResponse(
            content=str(content),
            tool_calls=tool_calls,
            usage=data.get("usage"),
            finish_reason=choice0.get("finish_reason"),
            raw=data,
        )

    def stream_call(self, request: ChatRequest):  # type: ignore[override]
        """
        OpenAI Chat Completions 流式输出：yield `delta.content` 文本片段。

        当前仅处理文本增量；如需 tool_calls 流式（复杂），建议仍走同步 `call` + 工具循环。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": _to_openai_messages(request.messages, provider=self.provider),
            "stream": True,
        }
        msg_shapes = [{"role": m.get("role"), "keys": sorted(list(m.keys()))} for m in payload["messages"]]
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens

        timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST", f"{self.url}/v1/chat/completions", json=payload, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        code, retryable = _map_status_to_llm_error(resp.status_code)
                        # httpx stream response：必须先 read() 才能安全访问 text
                        try:
                            raw_bytes = resp.read()
                            raw_text = raw_bytes.decode("utf-8", errors="replace")
                        except Exception:
                            raw_text = ""
                        msg = redact_secrets(raw_text, [self.api_key or ""])
                        diag = ""
                        if resp.status_code == 400:
                            diag = f" message_shapes={msg_shapes}"
                        raise LLMError(
                            code=code,  # type: ignore[arg-type]
                            message=f"http {resp.status_code}: {msg}{diag}",
                            retryable=retryable,
                            provider=self.provider,
                            request_id=request_id,
                            raw={"status_code": resp.status_code, "message_shapes": msg_shapes},
                        )

                    for line in resp.iter_lines():
                        if not line:
                            continue
                        s = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
                        s = s.strip()
                        if not s.startswith("data:"):
                            continue
                        data = s[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            import json as _json

                            obj = _json.loads(data)
                        except Exception:
                            continue
                        choice0 = (obj.get("choices") or [{}])[0] or {}
                        delta = choice0.get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield content
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

    def ping(self, timeout_ms: int = 1000) -> bool:
        """通过 `GET /v1/models` 判断服务是否可达。

        状态码小于 400 且无传输层异常时返回 True；`timeout_ms` 同时参与限制本次
        探测的建连与读取等待。
        """
        try:
            timeout = _client_timeout(
                connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms),
                timeout_ms=timeout_ms,
            )
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/v1/models", headers=headers)
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class OpenAICompatEmbeddingModel(EmbeddingModel):
    """OpenAI 兼容的文本向量模型。

    调用 `POST /v1/embeddings`，将一批输入文本映射为浮点向量。
    """

    def __init__(
        self,
        *,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """初始化向量模型名、服务根地址、可选 Bearer 密钥与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=_normalize_openai_api_root(url),
            api_key=api_key,
            capabilities=ModelCapabilities(),
            tags=tags,
            provider=provider or "openai_compat",
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: EmbeddingRequest) -> EmbeddingResponse:  # type: ignore[override]
        """对 `request.texts` 批量请求向量并组装 `EmbeddingResponse`。

        从响应 `data` 中依次读取 `embedding`，推断向量维度；HTTP 与网络异常抛
        `LLMError`。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {"model": self.model_name, "input": request.texts}
        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/v1/embeddings", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e

        if resp.status_code >= 400:
            code, retryable = _map_status_to_llm_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        data = resp.json()
        if isinstance(data.get("error"), dict):
            err = data["error"]
            msg = str(err.get("message") or err)
            code = str(err.get("code") or err.get("type") or "EMBEDDING_ERROR")
            raise LLMError(code, msg, True, self.provider, request_id, {"raw": data})

        items = data.get("data") or []
        vectors = [x.get("embedding") for x in items]
        vectors = [list(v) for v in vectors if isinstance(v, list)]
        if request.texts and not vectors:
            raise LLMError(
                "EMPTY_EMBEDDING",
                "embedding 接口未返回有效向量（data 为空或 embedding 字段无效）",
                True,
                self.provider,
                request_id,
                {"raw": data},
            )
        dim = len(vectors[0]) if vectors else 0
        return EmbeddingResponse(vectors=vectors, dimension=dim, usage=data.get("usage"), raw=data)

    def ping(self, timeout_ms: int = 1000) -> bool:
        """通过 `GET /v1/models` 判断服务是否可达（语义同对话模型的 `ping`）。"""
        try:
            timeout = _client_timeout(
                connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms),
                timeout_ms=timeout_ms,
            )
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/v1/models")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class OpenAICompatVisualModel(VisualModel):
    """复用 Chat Completions 的多模态视觉理解。

    将提示词与图像（URL 或 base64 data URL）写入单条 user message，请求
    `/v1/chat/completions`，适用于 Qwen-VL 等兼容端点。
    """

    def __init__(
        self,
        *,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """初始化视觉模型名、服务根地址、可选 Bearer 密钥与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=_normalize_openai_api_root(url),
            api_key=api_key,
            capabilities=ModelCapabilities(image_input=True),
            tags=tags,
            provider=provider or "openai_compat",
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: VisualRequest) -> VisualResponse:  # type: ignore[override]
        """根据图文内容生成 assistant 文本回复。

        有 `uri` 时作为 `image_url`；仅有 base64 时按 PNG 缺省 mime 组装 data
        URL。返回首条 choice 的正文及 usage/raw。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for img in request.images or []:
            if img.uri:
                content.append({"type": "image_url", "image_url": {"url": img.uri}})
            elif img.base64:
                mime = img.mime_type
                if not mime:
                    try:
                        raw = base64.standard_b64decode(img.base64, validate=False)
                        mime = guess_image_mime_from_bytes(raw[:32])
                    except Exception:
                        mime = "image/png"
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img.base64}"}})

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
        }

        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/v1/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e

        if resp.status_code >= 400:
            code, retryable = _map_status_to_llm_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        data = resp.json()
        choice0 = (data.get("choices") or [{}])[0]
        msg = (choice0.get("message") or {}).get("content") or ""
        return VisualResponse(content=str(msg), usage=data.get("usage"), raw=data)

    def ping(self, timeout_ms: int = 1000) -> bool:
        """通过 `GET /v1/models` 判断服务是否可达。"""
        try:
            timeout = _client_timeout(
                connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms),
                timeout_ms=timeout_ms,
            )
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/v1/models")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


class OpenAICompatVoiceModel(VoiceModel):
    """OpenAI 兼容的语音转写（ASR）。

    使用 `POST /v1/audio/transcriptions`，以 multipart 上传音频文件，符合
    OpenAI 及多数兼容网关的常见形态。
    """

    def __init__(
        self,
        *,
        model_name: str,
        source: str,
        url: str,
        api_key: str | None = None,
        provider: str | None = None,
        tags: list[str] | None = None,
        timeout_ms: int = 60000,
        connect_timeout_ms: int = 5000,
    ) -> None:
        """初始化语音模型名、服务根地址、可选 Bearer 密钥与 HTTP 超时。"""
        super().__init__(
            model_name=model_name,
            source=source,
            url=_normalize_openai_api_root(url),
            api_key=api_key,
            capabilities=ModelCapabilities(),
            tags=tags,
            provider=provider or "openai_compat",
        )
        self._timeout_ms = timeout_ms
        self._connect_timeout_ms = connect_timeout_ms

    def call(self, request: VoiceRequest) -> VoiceResponse:  # type: ignore[override]
        """提交本地音频并返回识别文本。

        支持 `audio.uri` 为 `file://` 本地路径，或 `audio.base64` 内存音频；
        其他远程 URI 不在此实现内下载，将抛出 `LLMError`。成功时读取 JSON 的
        `text` 填入 `VoiceResponse`。
        """
        request_id = str(request.metadata.get("request_id", ""))
        headers: dict[str, str] = {"x-request-id": request_id} if request_id else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        audio: AudioInput = request.audio
        files = {}
        if audio.uri and audio.uri.startswith("file://"):
            # file://path 形式
            path = audio.uri[len("file://") :]
            files["file"] = open(path, "rb")  # noqa: SIM115
        elif audio.base64:
            import base64
            import io

            raw = base64.b64decode(audio.base64)
            files["file"] = ("audio", io.BytesIO(raw))
        else:
            # 最小兜底：让上游以 URI 下载并转发（本实现不下载远程 URI）
            raise LLMError(
                code="BAD_REQUEST",
                message="audio.uri must be file://... or provide audio.base64",
                retryable=False,
                provider=self.provider,
                request_id=request_id,
            )

        data = {"model": self.model_name}
        if request.language:
            data["language"] = request.language
        if request.prompt:
            data["prompt"] = request.prompt

        try:
            timeout = _client_timeout(connect_timeout_ms=self._connect_timeout_ms, timeout_ms=self._timeout_ms)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.url}/v1/audio/transcriptions", headers=headers, data=data, files=files)
        except httpx.TimeoutException as e:
            raise LLMError("TIMEOUT", "http timeout", True, self.provider, request_id, {"error": str(e)}) from e
        except httpx.HTTPError as e:
            raise LLMError("NETWORK_ERROR", "http network error", True, self.provider, request_id, {"error": str(e)}) from e
        finally:
            f = files.get("file")
            try:
                if hasattr(f, "close"):
                    f.close()
            except Exception:
                pass

        if resp.status_code >= 400:
            code, retryable = _map_status_to_llm_error(resp.status_code)
            msg = redact_secrets(resp.text, [self.api_key or ""])
            raise LLMError(code, f"http {resp.status_code}: {msg}", retryable, self.provider, request_id, {"status_code": resp.status_code})

        out = resp.json()
        # 常见返回：{ "text": "..." }
        return VoiceResponse(text=str(out.get("text", "")), raw=out)

    def ping(self, timeout_ms: int = 1000) -> bool:
        """通过 `GET /v1/models` 判断服务是否可达。"""
        try:
            timeout = _client_timeout(
                connect_timeout_ms=min(self._connect_timeout_ms, timeout_ms),
                timeout_ms=timeout_ms,
            )
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{self.url}/v1/models")
            return r.status_code < 400
        except httpx.HTTPError:
            return False


# `llm` — 大模型抽象层

与具体供应商解耦：统一请求/响应类型、基类能力与错误码；具体 HTTP/OpenAI 协议实现在 `impl/` 中。

## 架构概览

```
llm/types.py          ← 请求/响应类型（ChatRequest、VisualRequest 等）
llm/base.py           ← 抽象基类（AbstractLLM、ChatModel 等）
llm/errors.py         ← LLMError + 敏感信息脱敏
llm/impl/
  http_api.py         ← 自定义 HTTP 网关（POST {url}/chat）
  openai_compat.py    ← OpenAI 兼容协议（siliconflow / vLLM / local）
```

## 类型体系（`types.py`）

### 消息类型

```python
LlmChatMessage  # LLM 接口层消息（role/content/metadata）
to_llm_chat_message(msg)  # 业务 Message → LLM Message 转换

Role = Literal["system", "user", "assistant", "tool"]
```

### 请求/响应

| 类型 | 说明 |
|------|------|
| `ChatRequest` | messages + temperature/top_p/max_output_tokens/tools/tool_choice |
| `ChatResponse` | content + tool_calls + usage + finish_reason + raw |
| `EmbeddingRequest` | texts + metadata |
| `EmbeddingResponse` | vectors + dimension + usage + raw |
| `VisualRequest` | prompt + images(VisualImage列表) + metadata |
| `VisualResponse` | content + images + usage + raw |
| `VoiceRequest` | audio(AudioInput) + metadata + language + prompt |
| `VoiceResponse` | text + segments + usage + raw |

### 图片输入

```python
VisualImage   # uri / base64 / mime_type 三选一
ImageInput    # 业务侧标准化前的图片输入
AudioInput    # 语音输入：uri / base64
```

## 抽象基类（`base.py`）

### `AbstractLLM`

公共基类，所有 LLM 客户端继承。

| 方法 | 说明 |
|------|------|
| `call(request)`（abstract）| 同步推理，子类实现 |
| `stream_call(request)` | 流式输出，默认抛 `NotImplementedError` |
| `ping(timeout_ms)`（abstract）| 轻量探活，超时/错误返回 False |
| `health()` | 返回健康信息字典（不含密钥）|
| `set_api_key(key)` | 运行时覆盖 API Key |

### `ModelCapabilities`

描述模型在协议层支持的能力开关：

```python
@dataclass(frozen=True)
class ModelCapabilities:
    stream: bool = False              # 流式输出
    tool_call: bool = False           # 工具调用
    json_schema: bool = False         # JSON Schema 输出
    max_input_tokens: int | None
    max_output_tokens: int | None
    dimension: int | None              # embedding 维度
    max_batch: int | None             # 最大批大小
    image_input: bool | None          # 图片输入
    image_max_size: int | None        # 最大图片尺寸
```

### 四种模型抽象

| 类 | 请求类型 | 响应类型 |
|---|---|---|
| `ChatModel` | `ChatRequest` | `ChatResponse` |
| `EmbeddingModel` | `EmbeddingRequest` | `EmbeddingResponse` |
| `VisualModel` | `VisualRequest` | `VisualResponse` |
| `VoiceModel` | `VoiceRequest` | `VoiceResponse` |

## 实现层（`impl/`）

### HttpApiChatModel（`http_api.py`）

自定义 HTTP 对话后端：将 `ChatRequest` JSON化后 `POST {url}/chat`。

| 方法 | 说明 |
|------|------|
| `call(request: ChatRequest)` | 调用 `{url}/chat`，返回 `ChatResponse` |
| `_classify_http_error(status_code)` | HTTP状态码 → (code, retryable)，映射：401/403→AUTH_FAILED、429→RATE_LIMITED、5xx→MODEL_UNAVAILABLE |
| `_client_timeout(...)` | httpx.Timeout 构造，建连/读写分离计时 |

同理还有 `HttpApiEmbeddingModel`、`HttpApiVisualModel`、`HttpApiVoiceModel`。

### OpenAICompatChatModel（`openai_compat.py`）

OpenAI 兼容协议：支持流式 `stream_call()`，兼容 siliconflow / vLLM / local 等。

| 方法 | 说明 |
|------|------|
| `call(request: ChatRequest)` | 调用 OpenAI 兼容 `/chat/completions` |
| `stream_call(request)` | 真流式输出（`data: {...}` 格式）|
| `_message_to_openai(msg)` | `LlmChatMessage` → OpenAI 消息格式，tool message 有特殊 provider 兼容处理 |
| `_to_openai_messages(msgs)` | 批量序列化 |

同理还有 `OpenAICompatEmbeddingModel`、`OpenAICompatVisualModel`、`OpenAICompatVoiceModel`。

## 公开导出（`__init__.py`）

```python
from SIA_agent.llm import (
    AbstractLLM, ChatModel, EmbeddingModel, VisualModel, VoiceModel,
    ChatRequest, ChatResponse, LlmChatMessage, Message,
    EmbeddingRequest, EmbeddingResponse,
    VisualImage, VisualRequest, VisualResponse,
    AudioInput, VoiceRequest, VoiceResponse,
    ToolCall, ImageInput,
    ModelCapabilities, to_llm_chat_message,
    LLMError,
)
```

其中 `Message` 为 `LlmChatMessage` 的向后兼容别名（见 `types.py`）。

## 开发注意事项

1. **Message**：业务层 `context.models.Message` 经 `to_llm_chat_message()` 转为 `LlmChatMessage`；模块导出的 `Message` 与 `LlmChatMessage` 在类型侧为别名关系（见 `types.py`）。
2. **provider 兼容**：OpenAI 兼容后端的 tool message 等在 `openai_compat.py` 中做了适配。
3. **超时**：建连与读写超时可分开配置（见各实现类与 `ModelManager`）。
4. **密钥**：`health()` 等勿输出明文 key；日志可用 `errors.redact_secrets` 思路脱敏（见 `llm/errors.py`）。

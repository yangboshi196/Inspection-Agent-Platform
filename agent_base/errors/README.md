# `errors` — 统一错误体系

覆盖 LLM、工具、Agent 等场景的统一 **`ErrorCode`** 与 **`AgentError`**，以及 SSE 用的 **`format_error_sse`**。

## 设计要点

- **`AgentError`**：`frozen` 数据类异常，字段与 SSE 错误 payload 对齐
- **`LLMError`**：`AgentError` 的别名（兼容旧代码）
- **`ToolError(...)`**：`exceptions.py` 中的**工厂函数**，生成带工具上下文的 `AgentError`（与 `tools.types.ToolResult.error` 所用的数据结构不同层）

## 错误码（节选）

详见 `codes.py`。分类示例：

- **LLM_***：鉴权、限流、超时、网络、模型不可用等
- **TOOL_***：工具不存在、参数非法、超时、上游失败等
- **AGENT_***：超步数、上下文溢出等
- **API_*** / **CTX_***：接口与会话相关（若在网关层使用）
- **INTERNAL_***：未归类内部错误

## 核心类型与函数

### `AgentError`

含 `code`、`message`、`retryable`、`details`、`provider`、`request_id` 等；提供 `to_sse_payload()`、`to_dict()`。

### 工厂与便捷函数

- `from_code(code, message=None, **kwargs)`
- `llm_error(sub_code, ...)`
- `tool_error(sub_code, ...)`
- `agent_error(sub_code, ...)`

### SSE

- `format_error_sse(error)`：将 `AgentError` 或普通 `Exception` 格式化为 SSE `data:` 行字符串
- `format_error_dict(...)`：直接构造错误字典
- `parse_error_sse` / `is_error_payload` / `error_message_of`：解析与判断辅助函数

示例：

```python
from SIA_agent.errors import AgentError, format_error_sse, from_code

raise from_code("LLM_TIMEOUT", "上游响应超时")

try:
    ...
except AgentError as e:
    line = format_error_sse(e)
```

## 开发注意事项

1. 优先用 **`from_code`** 或各层便捷函数构造异常，避免随意拼 `code` 字符串。
2. 向浏览器/SSE 推送错误时，优先 **`format_error_sse`**，保持前端字段一致。
3. **`ModelManager`** 内部重试逻辑会参考异常的 `retryable` 等语义（与具体实现保持一致）。

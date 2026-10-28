# `agent` — Agent 编排模块

本模块提供 **`BaseAgent`** 与两种开箱 Agent：**`SimpleAgent`**、**`ReActAgent`**，均依赖 `ModelManager`（大模型）+ `ToolRegistry`（工具注册）+ 可选的 `ContextManagerBase`（上下文）。

## 架构概览

```
BaseAgent（公共基座：工具解析、观察格式化）
├── SimpleAgent（main_agent.py：单轮 chat + 工具循环）
└── ReActAgent（react_agent.py：ReAct 多步推理 + 工具循环）

上下文（见 `context/`）：
  ContextManagerBase（ABC）
  ├── ContextManager（纯内存）
  └── HybridMemoryContextManager（内存 + Chroma + 摘要）
```

## 类说明

### BaseAgent（`base_agent.py`）

**职责**：公共工具解析、提示内工具列表格式化、观察结果模板化。子类实现 `stream()` 等具体流程。

| 方法 | 说明 |
|------|------|
| `_default_prompt_path()` | 子类覆盖：默认 system prompt 的 prompts 相对路径 |
| `_format_tools_for_prompt(tool_specs)` | 将工具规格列表格式化为可注入 system 的文本 |
| `_parse_tool_calls(text)` | 从模型输出解析工具调用（JSON 代码块、ReAct 标记、自然语言等） |
| `_is_valid_tool(name, args, tool_specs)` | 校验工具名与参数 |
| `_format_observation(tool_name, args, result)` | 将 `ToolResult` 格式化为下一轮 LLM 可读的 observation |

**工具调用 JSON 形态（推荐）**：

```json
{"tool_call": {"name": "工具名", "arguments": {"arg1": "value1"}}}
```

兼容：`action` / `action_input`，`tool_name` / `arguments`。

---

### SimpleAgent（`main_agent.py`）

**职责**：非 ReAct，直接 `call_chat` → 解析工具 → 执行 → 注入 observation，最多 `max_steps` 轮。

**构造函数（继承 `BaseAgent`）**：`model_manager`、`tool_registry`、`context_manager`（可选）、`system_prompt`（可选）、`max_steps`、`window_last_n`。

**SSE 事件**：`thinking_delta`（若有文本增量）、`tool_start`、`tool_end`、`done`、`error`。

| 方法 | 说明 |
|------|------|
| `stream(...)` | `session_id`、`user_input`、`model_name`、`record_user_message`；同步生成器，**非 async** |
| `run(...)` | 同步返回 `content`、`tool_trace` 等 |
| `build_turn_llm_messages(session_id=...)` | 组装 system + 摘要注入 + 历史窗口 |

**调用示例**：

```python
agent = SimpleAgent(
    model_manager=mm,
    tool_registry=registry,
    context_manager=ctx,  # 可选
)
for event in agent.stream(session_id="s1", user_input="你好"):
    print(event)
```

---

### ReActAgent（`react_agent.py`）

**职责**：多步推理；每步可流式输出思考，再解析工具并执行；无工具调用时输出最终回答或 `Final Answer` 段。

**构造函数**：与 `BaseAgent` 相同；`stream()` 另支持 `images`（图片路径列表，写入 system 占位符 `{image_paths}`）。

**SSE 事件**：`reasoning_start` / `reasoning_end`、`thinking_delta`、`tool_start` / `tool_end`、`delta`、`done`、`error`。

| 方法 | 说明 |
|------|------|
| `stream(...)` | 主入口，见上 |
| `_iter_chat_stream_text(...)` | 流式 chat，首 token 带超时保护，失败可降级整段 `call_chat` |
| `_format_observation` | 对 `rag_search_*` 工具使用缩短版 observation |

与 **SimpleAgent** 的主要差异：`stream()` 使用流式推理循环，`tool_start` 中带 `label`（来自 `ToolSpec.display_name`）。

---

## 依赖关系

```
BaseAgent
  ├── ModelManager（model_manager/manager.py）
  ├── ToolRegistry（tools/registry.py）
  ├── ContextManagerBase（可选，context/base.py）
  └── load_prompt（prompts/loader.py）

SimpleAgent / ReActAgent → 继承 BaseAgent
```

## 开发注意事项

1. **工具调用格式**：建议在 prompt 中约定 ``{"tool_call": {...}}``，并可放入 ` ```json ` 代码块。
2. **上下文写入**：在启用 `context_manager` 时，`stream()`/`run()` 内会对 user、assistant、observation 等调用 `add_message()`；回合结束会调用 `on_turn_end()`（若实现）。
3. **SSE 错误**：对外统一错误格式可使用 `SIA_agent.errors.format_error_sse()`。

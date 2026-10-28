# `prompts` — Prompt/文案集中管理

本目录集中存放 **默认 Agent 系统提示、RAG 识图与进度文案、上下文摘要相关模板** 等，通过 `loader.py` 按相对路径加载。

当前子目录仅 **`agent/`**、**`context/`**、**`rag/`**（业务专属文案可在应用仓库中自建目录或运行时传入字符串）。

## 目录结构

| 子目录 | 示例文件 | 职责 |
|--------|----------|------|
| `agent/` | `simple_agent_default.txt`、`react_agent_default.txt`、`tool_observation.txt` | SimpleAgent / ReActAgent 默认 system prompt；工具观察模板 |
| `rag/` | `doc_image_caption.txt`、`vision_inline.json`、`vision_progress.txt` | RAG 入库插图说明、占位与进度模板 |
| `context/` | `memory_headers.json`、`eviction_tool_placeholder.txt` | 摘要注入标题、淘汰占位 |

## loader.py — 统一加载接口

```python
from SIA_agent.prompts import load_prompt, load_prompt_fmt, load_prompt_json

text = load_prompt("agent/react_agent_default.txt")

text = load_prompt_fmt(
    "rag/doc_image_caption.txt",
    ordinal=1,
)

obj = load_prompt_json("rag/vision_inline.json")
```

**路径规则**：相对于 **`SIA_agent/prompts/`** 的 POSIX 子路径；禁止 `..`；自动规范换行。

## 占位符（`load_prompt_fmt`）

| 文件 | 占位符 | 说明 |
|------|--------|------|
| `rag/doc_image_caption.txt` | `{ordinal}` | 插图序号 |
| `agent/tool_observation.txt` | `tool_name`、`args`、`result` 等 | 见该文件内占位符 |

## 工具调用约定（写在 agent 提示词中）

```json
{"tool_call": {"name": "工具名", "arguments": {"arg1": "value1"}}}
```

常用：`agent/react_agent_default.txt`、`agent/simple_agent_default.txt`。

## 开发注意事项

1. 长 prompt 放入本目录并用 `load_prompt*` 加载。
2. `load_prompt_fmt` 的 kwargs 须与模板 `{xxx}` 一致。
3. 统一 UTF-8 编码。

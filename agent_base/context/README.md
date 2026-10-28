# `context` — 上下文与会话管理

三层记忆结构（长期 → 短期 → 摘要）：

```
长期记忆（ChromaDB 持久化）
  └─ ChromaSessionMemoryStore
      └─ save() / load()（会话快照，business_id + session_id）

短期记忆（内存消息窗口）
  └─ HybridMemoryContextManager._sessions[session_id].messages
      └─ add_message() → get_window()（滑动窗口读取）

摘要记忆（启发式压缩层）
  └─ HeuristicEvictionSummarizer
      └─ history_summary（追加式抄本，最大 12KB）
      └─ important_summary（短句收集，最大 6KB）
```

## 架构说明

### 两种 ContextManager 对比

| | `ContextManager` | `HybridMemoryContextManager` |
|---|---|---|
| 持久化 | 无 | ChromaDB（会话快照） |
| 摘要压缩 | 无 | `HeuristicEvictionSummarizer` |
| 适用场景 | 测试/简单场景 | 生产环境（多会话、长对话）|

### HybridMemoryContextManager 核心流程

#### 消息写入（`add_message`）

```
用户消息/模型输出/观察结果
    ↓
context_manager.add_message(role, content)
    ↓
保存到 _sessions[session_id].messages（全量永久）
    ↓
估算当前消息列表总 token 数
    ↓
若超过 window_max_messages → _summarize_until_fits()
    ↓
将早期消息内容追加合并到 history_summary
```

#### 上下文压缩（`_summarize_until_fits`）

- `history_summary`：以 `"role: content\n"` 追加式累积（最大 12KB）
- `important_summary`：收集 user/assistant 的短句（最大 6KB）
- 摘要**不删除**历史消息，仅用于大模型请求前的上下文压缩

#### 窗口读取（`get_window`）

```
get_window(session_id, last_n=20)   # 默认 20，与 Agent 的 window_last_n 配合
  ↓
若 summarized_upto > 0 → 返回「摘要 + 最近 N 条消息」
  ↓
否则 → 返回「最近 N 条消息」
  ↓
同时可在组装 LLM 请求前配合 get_summaries() 注入摘要
```

#### 持久化（`on_turn_end`）

```
on_turn_end(session_id)
    ↓
调用 ChromaSessionMemoryStore.save()
    ↓
upsert 全量 messages + history_summary + important_summary
    ↓
_doc_id = SHA256(business_id + "\n" + session_id)
```

#### 加载（`_ensure_loaded`）

```
首次访问 session 时触发
    ↓
调用 ChromaSessionMemoryStore.load()
    ↓
恢复 messages / history_summary / important_summary
    ↓
标记 loaded=True，后续不再重复加载
```

## 公开接口

### `ContextManagerBase`（`base.py`，ABC）

| 方法 | 说明 |
|------|------|
| `add_message(role, content, **kwargs)` | 添加消息，返回 `Message` |
| `get_window(session_id, last_n=...)` | 读取最近 N 条消息 |
| `get_summaries(session_id)` | 返回 `{"history_summary": str, "important_summary": str}`，子类实现 |
| `add_memory_item(type, content, importance)` | 添加记忆条目（默认纯内存）|
| `retrieve_memory(query, top_k)` | 关键词 + 重要度检索 |
| `on_turn_end(session_id)` | turn 结束时的回调（可选实现）|
| `delete_history(session_id)` | 删除会话历史（可选实现）|

### `HybridMemoryContextManager`（`hybrid_memory_context.py`）

| 方法/属性 | 说明 |
|------|------|
| `business_id`（property） | 所属业务 ID |
| `add_message(role, content, **kwargs)` | 写入消息 → 触发摘要压缩 → 返回 Message |
| `get_window(session_id, last_n=...)` | 返回摘要 + 窗口消息 |
| `get_summaries(session_id)` | 返回两类摘要 |
| `on_turn_end(session_id)` | Chroma 持久化全量数据 |
| `delete_history(session_id)` | 删除 Chroma 中的会话数据 + 内存缓存 |

### `ChromaSessionMemoryStore`（`chroma_memory_store.py`）

| 方法 | 说明 |
|------|------|
| `save(business_id, session_id, messages, history_summary, important_summary)` | 持久化会话快照 |
| `load(business_id, session_id)` | 加载会话快照，返回 `(messages, history_summary, important_summary)` |
| `delete(business_id, session_id)` | 删除 Chroma 中的会话文档 |
| `_stable_doc_id(business_id, session_id)` | SHA256 生成固定 doc_id |

### `HeuristicEvictionSummarizer`（`eviction_summarizer.py`）

纯启发式摘要，不调用 LLM：

| 摘要类型 | 生成规则 | 最大长度 |
|---|---|---|
| `history_summary` | 追加 `"role: content\n"` 抄本 | 12KB |
| `important_summary` | 收集 user/assistant 短句（<50字）| 6KB |

### `HybridMemoryConfig`（`hybrid_memory_config.py`）

```python
@dataclass
class HybridMemoryConfig:
    business_id: str
    window_max_messages: int = 40        # 窗口最大消息数
    evict_oldest_k: int = 5                # 每次压缩时合并的消息数
    max_history_chars: int = 12000         # history_summary 最大字符数
    max_important_chars: int = 6000        # important_summary 最大字符数
    chroma_persist_dir: str = "data/chroma_session_memory"
    collection_name: str = "session_memory"
```

## 数据模型

### `Message`（`models.py`）

```python
@dataclass(frozen=True)
class Message:
    id: str                    # UUID
    session_id: str
    role: str                  # "user" | "assistant" | "tool"
    content: str
    created_at: datetime
    token_count: int | None    # 估算 token 数（可选）
    metadata: dict[str, Any] | None
```

### `MemoryItem`（`models.py`）

```python
@dataclass(frozen=True)
class MemoryItem:
    id: str
    type: str                  # "fact" | "preference" | "note" | ...
    content: str
    importance: int            # 0-10，越高越重要
    created_at: datetime
    metadata: dict[str, Any] | None
```

## 开发注意事项

1. **消息写入时机**：所有 Agent 的 `stream()` 中，assistant 输出、observation、observation_error 都要调用 `add_message()` 持久化
2. **重复消息修复**：`add_message()` 返回 `msg.content` 后，复用而非在 `get_window()` 后再追加
3. **Chroma 兼容性**：使用 `embeddings=[[0.0]]` 避免 Chroma 自动下载 ONNX 模型
4. **session_id 一致性**：同一会话多次请求必须使用相同的 `session_id`
5. **摘要不影响历史**：`history_summary` 和 `important_summary` 仅用于 LLM 上下文压缩，不删除原始 `messages` 列表

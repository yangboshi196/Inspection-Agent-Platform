"""
HybridMemoryContext - 三层混合记忆上下文管理器。

融合纯内存会话窗口（ContextManager）+ Chroma 持久化快照（ChromaMemoryStore），
实现：近期消息保留在内存窗口 → 中期消息摘要压缩 → 长期记忆向量检索。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any

from ..prompts import load_prompt_json
from .base import ContextManagerBase
from .chroma_memory_store import ChromaSessionMemoryStore
from .eviction_summarizer import EvictionSummarizer, HeuristicEvictionSummarizer
from .hybrid_memory_config import HybridMemoryConfig
from .models import MemoryItem, Message


class _SessionState:
    __slots__ = ("messages", "history_summary", "important_summary", "summarized_upto", "loaded")

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.history_summary: str = ""
        self.important_summary: str = ""
        # 已经被“并入摘要”的历史消息条数（仅用于上下文压缩，不影响历史记录保留）
        self.summarized_upto: int = 0
        self.loaded: bool = False


class HybridMemoryContextManager(ContextManagerBase):
    """
    业务可复用：每个 `business_id` 建一个实例，共享同一套参数与 Chroma 目录。

    - 会话记录：`messages` 永久保留全量历史（用于渲染/审计/回放）。
    - 模型上下文：`get_window(...)` 仅取最近 N 条；当历史过长时，将更早的消息批量并入摘要以节省 token。
    - 摘要：仅用于请求大模型前的上下文压缩，不再删除历史消息。
    - 长期：`on_turn_end` 将全量消息 + 两类摘要 upsert 到 Chroma。
    """

    def __init__(
        self,
        *,
        config: HybridMemoryConfig,
        store: ChromaSessionMemoryStore | None = None,
        summarizer: EvictionSummarizer | None = None,
    ) -> None:
        self._config = config
        self._store = store or ChromaSessionMemoryStore(
            persist_dir=config.chroma_persist_dir,
            collection_name=config.collection_name,
        )
        self._summarizer: EvictionSummarizer = summarizer or HeuristicEvictionSummarizer(config)
        self._sessions: dict[str, _SessionState] = {}
        self._memory_items: dict[str, list[MemoryItem]] = {}  # 兼容旧 MemoryItem API

    @property
    def business_id(self) -> str:
        return self._config.business_id

    def _state(self, session_id: str) -> _SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState()
        return self._sessions[session_id]

    def _ensure_loaded(self, session_id: str) -> None:
        st = self._state(session_id)
        if st.loaded:
            return
        loaded = self._store.load(business_id=self._config.business_id, session_id=session_id)
        if loaded:
            msgs, hist, imp = loaded
            st.messages = msgs
            st.history_summary = hist
            st.important_summary = imp
            st.summarized_upto = 0
        st.loaded = True

    def _estimate_message_tokens(self, m: Message) -> int:
        if m.token_count is not None:
            return max(0, int(m.token_count))
        return max(1, len(m.content) // 4)

    def _total_window_tokens(self, messages: list[Message]) -> int:
        return sum(self._estimate_message_tokens(m) for m in messages)

    def _summarize_one_batch(self, st: _SessionState) -> None:
        """
        将一批“超出窗口的更早历史消息”并入摘要，但不删除历史记录。
        """
        max_n = max(1, int(self._config.window_max_messages))
        overflow_end = max(0, len(st.messages) - max_n)
        if overflow_end <= st.summarized_upto:
            return
        k = min(self._config.evict_oldest_k, overflow_end - st.summarized_upto)
        if k <= 0:
            return
        evicted = st.messages[st.summarized_upto : st.summarized_upto + k]
        hist, imp = self._summarizer.merge_evicted(
            history_summary=st.history_summary,
            important_summary=st.important_summary,
            evicted=evicted,
        )
        st.history_summary = hist
        st.important_summary = imp
        st.summarized_upto += k

    def _summarize_until_fits(self, st: _SessionState) -> None:
        """
        在不删除历史消息的前提下，尽可能把“窗口之外的早期历史”并入摘要。
        token 上限为可选：这里采用估算 + 逐批压缩策略（压缩的是“窗口之外”）。
        """
        max_tok = self._config.window_max_tokens
        safety = 0
        while True:
            max_n = max(1, int(self._config.window_max_messages))
            overflow_end = max(0, len(st.messages) - max_n)
            if overflow_end <= st.summarized_upto:
                break
            if max_tok is not None:
                window = st.messages[-max_n:]
                if self._total_window_tokens(window) <= int(max_tok):
                    break
            self._summarize_one_batch(st)
            safety += 1
            if safety > 10_000:
                break

    def get_all_messages(self, session_id: str) -> list[Message]:
        """返回会话的全量消息历史（用于前端渲染/回放）。"""
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        return list(st.messages)

    def get_summaries(self, session_id: str) -> tuple[str, str]:
        """返回 `(history_summary, important_summary)`，供拼 system / user 注入。"""
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        return st.history_summary, st.important_summary

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
        token_count: int | None = None,
    ) -> Message:
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        msg = Message(
            id=uuid.uuid4().hex,
            session_id=session_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            created_at=datetime.utcnow(),
            token_count=token_count,
            metadata=metadata or {},
        )
        st.messages.append(msg)
        # 不删除历史记录；仅在必要时把更早历史并入摘要，供模型上下文压缩使用
        self._summarize_until_fits(st)
        return msg

    def get_window(self, session_id: str, *, last_n: int = 20) -> list[Message]:
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        n = max(1, int(last_n))
        return st.messages[-n:]

    def on_turn_end(self, session_id: str) -> None:
        """每轮对话结束后调用：将当前窗口与两类摘要写入 Chroma。"""
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        self._store.save(
            business_id=self._config.business_id,
            session_id=session_id,
            messages=list(st.messages),
            history_summary=st.history_summary,
            important_summary=st.important_summary,
        )

    def delete_history(self, session_id: str) -> bool:
        """
        删除会话历史（持久化 + 内存）。

        用途：控制台“删除历史记录”。返回是否在持久化层存在并删除成功。
        """
        sid = (session_id or "").strip()
        if not sid:
            return False
        existed = self._store.delete(business_id=self._config.business_id, session_id=sid)
        self._sessions.pop(sid, None)
        self._memory_items.pop(sid, None)
        return existed

    # --- 兼容旧 ContextManager 的 MemoryItem API（仍可用于额外工程记忆）---

    def add_memory_item(
        self,
        *,
        session_id: str,
        type: str,
        content: str,
        importance: float = 0.5,
        source_range: dict | None = None,
    ) -> MemoryItem:
        now = datetime.utcnow()
        item = MemoryItem(
            id=uuid.uuid4().hex,
            session_id=session_id,
            type=type,  # type: ignore[arg-type]
            content=content,
            importance=float(importance),
            source_range=source_range,
            created_at=now,
            updated_at=now,
        )
        if session_id not in self._memory_items:
            self._memory_items[session_id] = []
        self._memory_items[session_id].append(item)
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        line = f"[{type}] {content}".strip()
        merged = (st.important_summary.strip() + "\n" + line).strip()
        max_imp = self._config.max_important_chars
        if len(merged) > max_imp:
            merged = merged[-max_imp:]
        st.important_summary = merged
        return item

    def retrieve_memory(self, session_id: str, *, query: str, top_k: int = 5) -> list[MemoryItem]:
        """关键词检索：扫描 MemoryItem + 两类摘要 + 窗口内文本。"""
        self._ensure_loaded(session_id)
        st = self._state(session_id)
        q = (query or "").strip().lower()
        items = list(self._memory_items.get(session_id) or [])

        synthetic: list[MemoryItem] = []
        if st.history_summary.strip():
            synthetic.append(
                MemoryItem(
                    id="__hist__",
                    session_id=session_id,
                    type="glossary",  # type: ignore[arg-type]
                    content=st.history_summary,
                    importance=0.6,
                    source_range=None,
                    created_at=None,
                    updated_at=None,
                )
            )
        if st.important_summary.strip():
            synthetic.append(
                MemoryItem(
                    id="__imp__",
                    session_id=session_id,
                    type="fact",  # type: ignore[arg-type]
                    content=st.important_summary,
                    importance=0.7,
                    source_range=None,
                    created_at=None,
                    updated_at=None,
                )
            )
        for m in st.messages[-50:]:
            synthetic.append(
                MemoryItem(
                    id=m.id,
                    session_id=session_id,
                    type="fact",  # type: ignore[arg-type]
                    content=f"{m.role}: {m.content}",
                    importance=0.3,
                    source_range=None,
                    created_at=m.created_at,
                    updated_at=m.created_at,
                )
            )

        pool = items + synthetic
        if not q:
            return sorted(pool, key=lambda x: x.importance, reverse=True)[: int(top_k)]

        scored: list[tuple[float, MemoryItem]] = []
        for it in pool:
            hay = it.content.lower()
            score = 0.0
            if q in hay:
                score += 1.0
            score += 0.1 * float(it.importance)
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[: int(top_k)]]


@lru_cache(maxsize=1)
def _memory_header_map() -> dict[str, Any]:
    return load_prompt_json("context/memory_headers.json")


def format_memory_for_prompt(history_summary: str, important_summary: str) -> str:
    """将两类摘要格式化为可拼进 system 的短文本（无内容则返回空串）。"""
    headers = _memory_header_map()
    parts: list[str] = []
    if history_summary.strip():
        parts.append(str(headers["history_header"]) + "\n" + history_summary.strip())
    if important_summary.strip():
        parts.append(str(headers["important_header"]) + "\n" + important_summary.strip())
    return "\n\n".join(parts)

"""
SIA_agent.context.base - 统一 Context 基座（ABC）

定义所有上下文管理器的抽象接口：
- 抽象方法（子类必须实现）：`add_message`、`get_window`
- 默认实现（可直接使用或覆盖）：`get_summaries`、`add_memory_item`、`retrieve_memory`

继承关系：
- ContextManager：纯内存版（基础版）
- HybridMemoryContextManager：混合版（内存 + Chroma 持久化 + 摘要压缩）

使用示例::

    from SIA_agent.context.base import ContextManagerBase

    class MyContextManager(ContextManagerBase):
        def add_message(self, *, session_id, role, content, **kwargs):
            ...
        def get_window(self, session_id, *, last_n=20):
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import MemoryItem, Message


class ContextManagerBase(ABC):
    """
    统一 Context 基座（ABC）：

    设计原则：
    - 抽象方法：子类必须实现的核心操作
    - 默认实现：提供纯内存版逻辑，子类可直接使用或覆盖

    继承关系：
    - ContextManager（基础版）：纯内存存储
    - HybridMemoryContextManager（混合版）：内存 + Chroma 持久化 + 摘要压缩
    """

    # ── 抽象方法（子类必须实现）──────────────────────

    @abstractmethod
    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
        token_count: int | None = None,
    ) -> "Message":
        """向指定会话追加一条消息。

        Args:
            session_id: 会话唯一标识符。
            role: 消息角色，取值范围见 Role 字面量类型（system/user/assistant/tool）。
            content: 消息正文内容。
            metadata: 扩展元数据字典，可包含 request_id、tool_call_id 等。
            token_count: 可选的消息 token 计数，用于上下文窗口管理和压缩。

        Returns:
            Message: 创建并持久化后的消息对象（包含自动生成的 id 和 created_at 时间戳）。

        Raises:
            NotImplementedError: 抽象方法，子类必须实现。
        """
        ...

    @abstractmethod
    def get_window(self, session_id: str, *, last_n: int = 20) -> list["Message"]:
        """返回会话最近 N 条消息。

        Args:
            session_id: 会话唯一标识符。
            last_n: 返回消息数量上限，默认为 20。超出的旧消息会被截断。

        Returns:
            list[Message]: 最近 last_n 条消息组成的列表，按时间顺序排列。
            如果会话不存在或无消息，返回空列表。

        Raises:
            NotImplementedError: 抽象方法，子类必须实现。
        """
        ...

    # ── 默认实现（子类可直接使用或覆盖）───────────────

    def get_summaries(self, session_id: str) -> tuple[str, str]:
        """
        返回 (history_summary, important_summary)。

        基础版默认返回空。Hybrid 版会覆盖以返回真实摘要。
        """
        return "", ""

    def add_memory_item(
        self,
        *,
        session_id: str,
        type: str,
        content: str,
        importance: float = 0.5,
        source_range: dict | None = None,
    ) -> "MemoryItem":
        """
        写入一条会话级记忆（默认实现：纯内存存储）。

        子类如需扩展（如合并到摘要、持久化），请覆盖此方法。
        """
        from .models import MemoryItem
        import uuid

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
        self._add_memory_item_impl(session_id, item)
        return item

    def _add_memory_item_impl(self, session_id: str, item: "MemoryItem") -> None:
        """
        子类可覆盖此方法来自定义存储逻辑。

        默认实现不执行任何操作（基础版由子类直接管理 _memory）。
        """
        pass

    def retrieve_memory(
        self,
        session_id: str,
        *,
        query: str,
        top_k: int = 5,
    ) -> list["MemoryItem"]:
        """
        检索记忆（默认实现：关键词匹配 + 重要度排序）。

        子类如需扩展（如搜索摘要、Chroma 向量检索），请覆盖此方法。
        """
        items = self._get_memory_items_impl(session_id)
        if not items:
            return []

        q = (query or "").strip().lower()
        if not q:
            return sorted(items, key=lambda x: x.importance, reverse=True)[:top_k]

        scored: list[tuple[float, "MemoryItem"]] = []
        for it in items:
            hay = it.content.lower()
            score = 0.0
            if q in hay:
                score += 1.0
            score += 0.1 * float(it.importance)
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:top_k]]

    def _get_memory_items_impl(self, session_id: str) -> list["MemoryItem"]:
        """
        子类可覆盖此方法来自定义记忆检索逻辑。

        默认返回空列表。
        """
        return []

    # ── 可选方法（子类可选实现）─────────────────────

    def on_turn_end(self, session_id: str) -> None:
        """每轮对话结束后调用。默认空实现（Hybrid 版会覆盖）。"""
        pass

    def delete_history(self, session_id: str) -> bool:
        """
        删除会话历史。默认返回 False（Hybrid 版会覆盖）。
        """
        return False

    def get_all_messages(self, session_id: str) -> list["Message"]:
        """
        返回会话全量消息。默认返回窗口消息。
        子类如需全量历史请覆盖。
        """
        return self.get_window(session_id, last_n=999999)

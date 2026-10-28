"""
SIA_agent.context.manager - 纯内存版上下文管理器

最小可用上下文管理（进程内内存存储）：
- messages：按 session_id 追加与窗口读取
- memory_items：按 session_id 保存；检索先做关键词匹配

适用场景：
- 开发 / 测试环境
- 不需要跨进程持久化的轻量应用

不适用场景（请改用 HybridMemoryContextManager）：
- 需要会话快照持久化
- 需要 Chroma 向量检索
- 需要摘要压缩
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from .base import ContextManagerBase
from .models import MemoryItem, Message


class ContextManager(ContextManagerBase):
    """
    最小可用上下文管理（内存版）：
    - messages：按 session_id 追加与窗口读取
    - memory_items：按 session_id 保存；检索先做关键词匹配
    """

    def __init__(self) -> None:
        """初始化空的会话消息表与记忆表（进程内内存存储）。"""
        self._messages: dict[str, list[Message]] = defaultdict(list)
        self._memory: dict[str, list[MemoryItem]] = defaultdict(list)

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
        token_count: int | None = None,
    ) -> Message:
        """向指定会话追加一条消息并返回持久化后的 `Message` 对象。"""
        msg = Message(
            id=uuid.uuid4().hex,
            session_id=session_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            created_at=datetime.utcnow(),
            token_count=token_count,
            metadata=metadata or {},
        )
        self._messages[session_id].append(msg)
        return msg

    def get_window(self, session_id: str, *, last_n: int = 20) -> list[Message]:
        """取会话最近 `last_n` 条消息，用于拼进模型上下文窗口。"""
        msgs = self._messages.get(session_id) or []
        return msgs[-last_n:]

    def _add_memory_item_impl(self, session_id: str, item: MemoryItem) -> None:
        """存储 MemoryItem 到内存字典。"""
        self._memory[session_id].append(item)

    def _get_memory_items_impl(self, session_id: str) -> list[MemoryItem]:
        """从内存字典检索 MemoryItem。"""
        return self._memory.get(session_id, [])

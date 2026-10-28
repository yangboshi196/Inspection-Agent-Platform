"""Context 模块 - 会话消息与记忆数据结构

定义会话上下文管理的核心数据类型：
- Message       : 会话消息（role/content/metadata/时间戳）
- MemoryItem    : 记忆条目（类型/内容/重要度/向量）
- Role          : 消息角色字面量（system/user/assistant/tool）
- MemoryType    : 记忆类型字面量（decision/fact/constraint/preference/glossary/todo）

所有 dataclass 均 frozen=True，保证不可变性，适用于跨进程传输和日志记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]
MemoryType = Literal["decision", "fact", "constraint", "preference", "glossary", "todo"]


@dataclass(frozen=True)
class Message:
    """会话消息结构（不可变）。

    Attributes:
        id: 全局唯一消息 ID（UUID hex）。
        session_id: 所属会话 ID。
        role: 消息角色（system/user/assistant/tool）。
        content: 消息正文。
        created_at: 创建时间（UTC）。
        token_count: token 计数（可选，用于上下文压缩）。
        metadata: 扩展元数据（如 request_id、tool_call_id 等）。
    """
    id: str
    session_id: str
    role: Role
    content: str
    created_at: datetime
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryItem:
    """记忆条目结构（不可变）。

    用于跨会话持久化和向量检索。

    Attributes:
        id: 全局唯一记忆 ID。
        session_id: 所属会话 ID。
        type: 记忆类型（decision/fact/constraint/preference/glossary/todo）。
        content: 记忆正文。
        importance: 重要度评分（0.0~1.0），用于检索排序。
        source_range: 来源范围（如对应消息索引区间）。
        created_at: 创建时间。
        updated_at: 更新时间。
        embedding: 向量表示（可选，用于向量检索）。
    """
    id: str
    session_id: str
    type: MemoryType
    content: str
    importance: float = 0.5
    source_range: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    embedding: list[float] | None = None



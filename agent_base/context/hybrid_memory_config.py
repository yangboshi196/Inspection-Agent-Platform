"""
SIA_agent.context.hybrid_memory_config - 混合记忆配置

参数说明：
- window_max_messages：短期窗口最大消息数（默认 40）
- evict_oldest_k：每次淘汰最旧消息条数（默认 5）
- max_history_chars：历史摘要最大字符数（默认 12000）
- max_important_chars：重要摘要最大字符数（默认 6000）
- chroma_persist_dir：Chroma 持久化目录（默认 ".chroma_agent_memory"）
- collection_name：Chroma collection 名称
- window_max_tokens：可选，token 级别窗口限制
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HybridMemoryConfig:
    """
    按业务实例化一份配置即可复用同一套记忆逻辑（不同 `business_id` 各建一个 Manager）。

    - 短期：仅保留最近 `window_max_messages` 条会话消息（窗口）。
    - 超窗：每次将最旧的 `evict_oldest_k` 条移出窗口，经 summarizer 写入「历史摘要」「重要信息摘要」。
    - 长期：每轮对话结束将「窗口 + 两类摘要」持久化到 Chroma（见 `HybridMemoryContextManager.on_turn_end`）。
    """

    business_id: str
    window_max_messages: int = 40
    evict_oldest_k: int = 5
    max_history_chars: int = 12_000
    max_important_chars: int = 6_000
    chroma_persist_dir: str | Path = ".chroma_agent_memory"
    collection_name: str = "agent_session_memory"
    window_max_tokens: int | None = None

"""Context 模块 - 三层记忆结构统一出口

本模块实现 Agent 的三层记忆体系：
- 长期记忆  : ChromaDB 持久化（ChromaSessionMemoryStore）
- 短期记忆  : 内存窗口消息（messages[]，按 session_id 管理）
- 摘要记忆  : history_summary + important_summary（HeuristicEvictionSummarizer）

两类 ContextManager：
- ContextManager               : 纯内存版（适合轻量场景）
- HybridMemoryContextManager   : 混合版（内存+Chroma+摘要，适合生产环境）

Usage:
    from SIA_agent.context import HybridMemoryContextManager, HybridMemoryConfig

    config = HybridMemoryConfig(business_id="biz-001")
    ctx = HybridMemoryContextManager(config=config)
    ctx.add_message(session_id="s1", role="user", content="你好")
    msgs = ctx.get_window(session_id="s1", last_n=20)
"""

from .base import ContextManagerBase
from .chroma_memory_store import ChromaSessionMemoryStore
from .eviction_summarizer import EvictionSummarizer, HeuristicEvictionSummarizer
from .hybrid_memory_config import HybridMemoryConfig
from .hybrid_memory_context import HybridMemoryContextManager, format_memory_for_prompt
from .manager import ContextManager
from .models import MemoryItem, Message

__all__ = [
    "ContextManagerBase",
    "ChromaSessionMemoryStore",
    "ContextManager",
    "EvictionSummarizer",
    "HeuristicEvictionSummarizer",
    "HybridMemoryConfig",
    "HybridMemoryContextManager",
    "MemoryItem",
    "Message",
    "format_memory_for_prompt",
]


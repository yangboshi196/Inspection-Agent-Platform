"""
SIA_agent.context.eviction_summarizer - 窗口淘汰摘要策略

将移出上下文窗口的消息合并为两类摘要：
- EvictionSummarizer（Protocol）：摘要策略接口，子类可实现任意合并逻辑
- HeuristicEvictionSummarizer（默认）：纯规则实现，不调用 LLM
  - 历史摘要：追加对话抄本（按 max_history_chars 截断）
  - 重要摘要：收集 user/assistant 短句（按 max_important_chars 截断）

生产环境可替换为基于 LLM 的实现（同一 Protocol）。
"""

from __future__ import annotations

from typing import Protocol

from ..prompts import load_prompt
from .hybrid_memory_config import HybridMemoryConfig
from .models import Message


class EvictionSummarizer(Protocol):
    """将移出窗口的若干条消息并入「历史摘要 / 重要信息摘要」。"""

    def merge_evicted(
        self,
        *,
        history_summary: str,
        important_summary: str,
        evicted: list[Message],
    ) -> tuple[str, str]:
        ...


class HeuristicEvictionSummarizer:
    """
    不调用模型的默认合并：历史摘要追加对话抄本（截断）；重要摘要收集 user/assistant 短句。
    生产环境可替换为基于 LLM 的实现（同一 Protocol）。
    """

    def __init__(self, config: HybridMemoryConfig) -> None:
        self._max_history = int(config.max_history_chars)
        self._max_important = int(config.max_important_chars)
        self._tool_placeholder = load_prompt("context/eviction_tool_placeholder.txt")

    def merge_evicted(
        self,
        *,
        history_summary: str,
        important_summary: str,
        evicted: list[Message],
    ) -> tuple[str, str]:
        lines: list[str] = []
        imp_lines: list[str] = []
        for m in evicted:
            text = (m.content or "").strip()
            if not text and m.role == "tool":
                text = self._tool_placeholder
            line = f"{m.role}: {text}"
            lines.append(line[:2_000])
            if m.role in ("user", "assistant") and text:
                snippet = text.replace("\n", " ")[:400]
                if snippet:
                    imp_lines.append(f"- {snippet}")

        block = "\n".join(lines)
        hist = (history_summary.strip() + "\n\n---\n" + block).strip()
        if len(hist) > self._max_history:
            hist = hist[-self._max_history :]

        imp_block = "\n".join(imp_lines)
        imp = (important_summary.strip() + "\n" + imp_block).strip()
        if len(imp) > self._max_important:
            imp = imp[-self._max_important :]

        return hist, imp

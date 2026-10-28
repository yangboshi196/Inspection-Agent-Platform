"""
SIA_agent.rag.rag_search_tool - RAG 检索工具封装

将 KnowledgeBase 的向量检索能力封装为 Agent 可调用的 Tool：
- 注册到 ToolRegistry 后由 ReActAgent / SimpleAgent 等调用
- 工具名格式：`rag_search_{knowledge_base.id}`
- 参数：query（检索词）、top_k（返回条数）、filters（metadata 等值过滤）、need_citation（是否附引用）
"""

from __future__ import annotations

from typing import Any

from ..tools.base import Tool, ToolSpec
from ..tools.types import ToolError, ToolResult
from .knowledge_base import KnowledgeBase


class RagSearchTool(Tool):
    """把某个 `KnowledgeBase` 的向量检索封装为 Agent 可调用的 Tool。"""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        """`knowledge_base`：要暴露检索能力的目标知识库实例。"""
        self._knowledge_base = knowledge_base
        kb_label = (knowledge_base.cfg.name or "").strip() or knowledge_base.cfg.id
        super().__init__(
            ToolSpec(
                name=f"rag_search_{knowledge_base.cfg.id}",
                description=f"对知识库 '{knowledge_base.cfg.name}' 做向量检索，返回 contexts（可带引用）",
                input_schema={
                    "query": "string",
                    "top_k": "int (optional)",
                    "filters": "object (optional)",
                    "need_citation": "bool (optional)",
                },
                output_schema={"contexts": "array", "query": "string", "request_id": "string"},
                timeout_ms=20000,
                side_effect=False,
                idempotent=True,
                display_name=f"知识库 · {kb_label}",
            )
        )

    def invoke(self, arguments: dict[str, Any], *, request_id: str | None = None) -> ToolResult:
        """执行向量检索；`arguments` 需含 `query`，可选 `top_k` / `filters` / `need_citation`。"""
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="INVALID_ARGUMENT",
                    message="missing 'query' (string)",
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=False,
                ),
            )
        top_k = arguments.get("top_k")
        filters = arguments.get("filters")
        need_citation = arguments.get("need_citation")
        try:
            out = self._knowledge_base.search(
                query=query,
                request_id=str(request_id or ""),
                top_k=int(top_k) if top_k is not None else None,
                filters=dict(filters) if isinstance(filters, dict) else None,
                need_citation=bool(need_citation) if need_citation is not None else None,
            )
            return ToolResult(ok=True, tool_name=self.spec.name, request_id=request_id, data=out)
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="UPSTREAM_ERROR",
                    message=str(e),
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=True,
                ),
            )

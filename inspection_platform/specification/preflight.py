"""规范抽取前置检查。"""

from __future__ import annotations

import time
from typing import Any


def preflight_extract_documents(
    *,
    kb_id: str,
    doc_ids: list[str],
    model_manager: Any,
    embedding_model_name: str | None,
) -> dict[str, Any]:
    """
    抽取前校验：文档存在、原文在盘、指定 kb 已向量化。

    返回 ``ready`` 与逐文档 ``documents`` 明细；``ready=False`` 时 ``messages`` 汇总原因。
    """
    from inspection_platform.document.service import DocumentService
    from inspection_platform.knowledge.ingest_service import KnowledgeIngestService

    kb = (kb_id or "default").strip() or "default"
    docs = [d.strip() for d in doc_ids if d and str(d).strip()]
    if not docs:
        return {
            "ready": False,
            "kb_id": kb,
            "documents": [],
            "messages": ["doc_ids 不能为空"],
        }

    doc_svc = DocumentService()
    doc_svc.ensure_ready()
    ks = KnowledgeIngestService(model_manager, embedding_model_name=embedding_model_name)

    rows: list[dict[str, Any]] = []
    messages: list[str] = []

    for did in docs:
        row: dict[str, Any] = {
            "doc_id": did,
            "document_exists": False,
            "file_present": False,
            "vectorized": False,
            "document_name": "",
            "chunk_count": 0,
            "ok": False,
        }
        try:
            rec = doc_svc.get_by_id(did)
            row["document_exists"] = True
            row["document_name"] = rec.name
            path = doc_svc.resolve_path(did)
            row["file_present"] = path.is_file()
            if not row["file_present"]:
                messages.append(f"文档 {did} 原文文件缺失")
        except KeyError:
            messages.append(f"文档库中不存在 document_id={did!r}")

        if row["document_exists"]:
            chunks = 0
            for attempt in range(4):
                chunks = ks.count_document_chunks(kb_id=kb, doc_id=did)
                if chunks > 0:
                    break
                if attempt < 3:
                    time.sleep(0.4)
            row["chunk_count"] = chunks
            row["vectorized"] = chunks > 0
            if not row["vectorized"]:
                messages.append(
                    f"文档 {did} 在知识库 kb_id={kb!r} 中尚未向量化，请先 POST /api/knowledge/ingest"
                )

        row["ok"] = (
            row["document_exists"] and row["file_present"] and row["vectorized"]
        )
        rows.append(row)

    ready = all(r["ok"] for r in rows)
    return {
        "ready": ready,
        "kb_id": kb,
        "documents": rows,
        "messages": messages,
    }

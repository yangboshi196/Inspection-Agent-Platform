"""
SIA_agent.rag.config - RAG 配置类型

定义知识库配置的数据类：
- ChunkConfig：分块参数（chunk_size / chunk_overlap）
- RetrievalConfig：检索参数（top_k / candidate_k / min_score / rerank / citation）
- IndexConfig：索引参数（persist_dir / meta_fields）
- KnowledgeBaseConfig：知识库顶层配置（id / name / doc_dir / rebuild_policy / embedding）
- parse_rag_config()：从 JSON 字典解析为 KnowledgeBaseConfig 列表
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


RebuildPolicy = Literal["manual", "on_change"]
IndexType = Literal["vector"]


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int = 1000
    chunk_overlap: int = 150


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 5
    candidate_k: int = 15
    # 向量相似度下限（score = 1 - distance，范围约 0~1）；需在 JSON 中写 `0` 可关闭过滤
    min_score: float | None = 0.75
    enable_rerank: bool = False
    need_citation: bool = True


@dataclass(frozen=True)
class IndexConfig:
    type: IndexType = "vector"
    persist_dir: str = ".rag_index"
    meta_fields: list[str] | None = None


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    id: str
    name: str
    doc_dir: str
    rebuild_policy: RebuildPolicy = "manual"
    chunk: ChunkConfig = ChunkConfig()
    embedding_model_name: str | None = None
    retrieval: RetrievalConfig = RetrievalConfig()
    index: IndexConfig = IndexConfig()


def parse_rag_config(data: dict[str, Any]) -> list[KnowledgeBaseConfig]:
    """
    解析 RAG 顶层 JSON（含 `knowledge_bases` 数组），校验必填字段并转为 `KnowledgeBaseConfig` 列表。

    若某项格式不合法会抛出 `ValueError`，错误信息中带数组下标便于定位。
    """
    kbs = data.get("knowledge_bases") or []
    res: list[KnowledgeBaseConfig] = []
    for i, kb in enumerate(kbs):
        if not isinstance(kb, dict):
            raise ValueError(f"knowledge_bases[{i}] must be object")
        kb_id = str(kb.get("id") or "").strip()
        if not kb_id:
            raise ValueError(f"knowledge_bases[{i}]: missing 'id'")
        name = str(kb.get("name") or kb_id)
        doc_dir = str(kb.get("doc_dir") or "").strip()
        if not doc_dir:
            raise ValueError(f"knowledge_bases[{i}]: missing 'doc_dir'")

        chunk = kb.get("chunk") or {}
        chunk_cfg = ChunkConfig(
            chunk_size=int(chunk.get("chunk_size") or 1000),
            chunk_overlap=int(chunk.get("chunk_overlap") or 150),
        )

        retrieval = kb.get("retrieval") or {}
        top_k = int(retrieval.get("top_k") or 5)
        if "min_score" not in retrieval or retrieval.get("min_score") is None:
            min_score: float | None = 0.75
        else:
            min_score = float(retrieval.get("min_score"))
        retrieval_cfg = RetrievalConfig(
            top_k=top_k,
            candidate_k=int(retrieval.get("candidate_k") or (top_k * 3)),
            min_score=min_score,
            enable_rerank=bool(retrieval.get("enable_rerank") or False),
            need_citation=bool(retrieval.get("need_citation") if "need_citation" in retrieval else True),
        )

        index = kb.get("index") or {}
        index_cfg = IndexConfig(
            type=str(index.get("type") or "vector"),  # type: ignore[arg-type]
            persist_dir=str(index.get("persist_dir") or ".rag_index"),
            meta_fields=list(index.get("meta_fields") or []) or None,
        )

        embedding = kb.get("embedding") or {}
        embedding_model_name = embedding.get("model_name")

        res.append(
            KnowledgeBaseConfig(
                id=kb_id,
                name=name,
                doc_dir=doc_dir,
                rebuild_policy=str(kb.get("rebuild_policy") or "manual"),  # type: ignore[arg-type]
                chunk=chunk_cfg,
                embedding_model_name=str(embedding_model_name) if embedding_model_name else None,
                retrieval=retrieval_cfg,
                index=index_cfg,
            )
        )
    return res


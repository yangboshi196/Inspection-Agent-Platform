"""
SIA_agent.rag.knowledge_base - 知识库核心类

全流程管理：
1. 文档解析（PDF / DOCX / TXT / MD）
2. 图像富化（调用多模态模型为图片生成文字描述，插入正文）
3. 语义分块（按策略切分文本）
4. 向量写入（Chroma）
5. 上下文检索（query → embedding → Chroma → 重排序 → 引用拼接）

使用示例::

    from SIA_agent.model_manager.manager import ModelManager
    from SIA_agent.rag.knowledge_base import KnowledgeBase
    from SIA_agent.rag.config import parse_rag_config, KnowledgeBaseConfig

    model_manager = ModelManager.from_json(config)
    cfg = parse_rag_config(data)[0]
    kb = KnowledgeBase(cfg, model_manager=model_manager)
    kb.ingest_dir()
    results = kb.retrieve("安全生产规范有哪些")
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from docx import Document

from ..llm.types import EmbeddingRequest
from ..model_manager.manager import ModelManager
from .chroma_vector_store import ChromaVectorStore
from .chunking import chunk_text_by_strategy
from .config import KnowledgeBaseConfig
from .doc_vision_enrich import enrich_document_text_for_indexing
from .embedded_chunk import EmbeddedChunk


class KnowledgeBase:
    """按配置管理文档分块、向量写入 Chroma、以及检索上下文。"""

    def __init__(self, cfg: KnowledgeBaseConfig, *, model_manager: ModelManager) -> None:
        """绑定知识库配置与全局 `ModelManager`（用于拉取 embedding）。"""
        self.cfg = cfg
        self._model_manager = model_manager
        self._persist_dir = Path(cfg.index.persist_dir)
        self._vector_store = ChromaVectorStore(persist_dir=self._persist_dir, kb_id=cfg.id)

    @property
    def indexed_chunk_count(self) -> int:
        """当前 Chroma 集合中已写入的分块数量。"""
        return self._vector_store.chunk_count

    @property
    def size(self) -> int:
        """与历史属性名兼容：当前索引中的分块条数。"""
        return self.indexed_chunk_count

    def _extract_text(self, p: Path) -> str:
        suf = p.suffix.lower()
        if suf in (".txt", ".md"):
            return p.read_text(encoding="utf-8", errors="ignore")
        if suf == ".pdf":
            reader = PdfReader(str(p))
            parts: list[str] = []
            for page in reader.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    parts.append(t)
            return "\n\n".join(parts)
        if suf == ".docx":
            doc = Document(str(p))
            paras = [para.text for para in doc.paragraphs if (para.text or "").strip()]
            return "\n".join(paras)
        return ""

    def ingest_file(
        self,
        p: Path,
        *,
        request_id: str,
        strategy: str = "fixed",
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        replace_same_name: bool = True,
        vision_model_name: str | None = None,
        embedding_model_name: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        增量入库：仅对单个文件做提取->分块->embedding->写入，不重置整个 collection。

        - replace_same_name: True 时会按 doc_name 删除旧分片，避免重复堆积
        """
        if not p.is_file():
            raise FileNotFoundError(str(p))
        if p.suffix.lower() not in (".txt", ".md", ".pdf", ".docx"):
            return {"ok": False, "reason": "unsupported file type", "doc_name": p.name, "indexed_chunks": 0}

        strategy_key = (strategy or "fixed").strip().lower()
        use_vision = strategy_key == "vision_paragraph"
        inner_strategy = "paragraph" if use_vision else strategy_key
        vision_stats: dict[str, Any] | None = None
        if use_vision:
            vmn = (vision_model_name or "").strip() or None
            raw, vision_stats = enrich_document_text_for_indexing(
                p,
                model_manager=self._model_manager,
                request_id=request_id,
                vision_model_name=vmn,
                progress_callback=progress_callback,
            )
        else:
            raw = self._extract_text(p)
        if not raw.strip():
            out_empty: dict[str, Any] = {"ok": False, "reason": "empty text", "doc_name": p.name, "indexed_chunks": 0}
            if vision_stats is not None:
                out_empty["vision"] = vision_stats
            return out_empty

        cs = int(chunk_size) if chunk_size is not None else int(self.cfg.chunk.chunk_size)
        co = int(chunk_overlap) if chunk_overlap is not None else int(self.cfg.chunk.chunk_overlap)
        parts = chunk_text_by_strategy(raw, strategy=inner_strategy, chunk_size=cs, chunk_overlap=co)
        if progress_callback:
            try:
                progress_callback(
                    {
                        "type": "progress",
                        "stage": "chunk",
                        "message": f"已分块 {len(parts)} 段",
                        "chunks": len(parts),
                        "percent": 78,
                    }
                )
            except Exception:
                pass
        if not parts:
            out_no_chunks: dict[str, Any] = {"ok": False, "reason": "no chunks", "doc_name": p.name, "indexed_chunks": 0}
            if vision_stats is not None:
                out_no_chunks["vision"] = vision_stats
            return out_no_chunks

        if replace_same_name:
            self._vector_store.delete_by_filters({"doc_name": p.name})

        extra = {k: v for k, v in (extra_metadata or {}).items() if v is not None}
        metas: list[dict[str, Any]] = []
        for idx, _ in enumerate(parts):
            chunk_id = f"{p.name}:{idx}:{uuid.uuid4().hex[:8]}"
            meta = {
                "doc_name": p.name,
                "doc_path": str(p),
                "chunk_id": chunk_id,
                "kb_id": self.cfg.id,
            }
            meta.update(extra)
            metas.append(meta)

        emb_override = (embedding_model_name or "").strip() or None
        emb_model_name = emb_override or self.cfg.embedding_model_name
        if progress_callback:
            try:
                progress_callback(
                    {
                        "type": "progress",
                        "stage": "embedding",
                        "message": "向量化并写入索引…",
                        "percent": 88,
                    }
                )
            except Exception:
                pass
        vectors = self._model_manager.call_embedding(
            EmbeddingRequest(texts=parts, metadata={"request_id": request_id, "doc_name": p.name}),
            model_name=emb_model_name,
        ).vectors
        chunks: list[EmbeddedChunk] = []
        for text, vec, meta in zip(parts, vectors, metas, strict=False):
            chunks.append(EmbeddedChunk(chunk_id=meta["chunk_id"], text=text, vector=list(vec), meta=meta))
        self._vector_store.add_embedded_chunks(chunks)
        if progress_callback:
            try:
                progress_callback({"type": "progress", "stage": "finish", "message": "完成", "percent": 100})
            except Exception:
                pass
        out_ok: dict[str, Any] = {"ok": True, "doc_name": p.name, "indexed_chunks": len(chunks)}
        if vision_stats is not None:
            out_ok["vision"] = vision_stats
        return out_ok

    def count_chunks_for_doc(self, doc_name: str) -> int:
        return int(self._vector_store.count_by_filters({"doc_name": str(doc_name)}))

    def purge_doc_vectors(self, doc_name: str) -> int:
        """删除某个源文件在向量库中的全部分片（按 metadata `doc_name` 过滤）。"""
        return int(self._vector_store.delete_by_filters({"doc_name": str(doc_name)}))

    def rebuild(self, *, request_id: str) -> None:
        """
        扫描 `doc_dir` 下 txt/md/pdf/docx，提取文本后分块，批量求 embedding 并写入 Chroma（会先清空本库 collection）。
        无可用文本时仅重置为空索引。
        """
        doc_dir = Path(self.cfg.doc_dir)
        if not doc_dir.exists():
            raise FileNotFoundError(f"doc_dir not found: {doc_dir}")

        self._vector_store.reset()

        chunks: list[EmbeddedChunk] = []
        texts: list[str] = []
        metas: list[dict[str, Any]] = []

        for p in sorted(doc_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".txt", ".md", ".pdf", ".docx"):
                continue
            raw = self._extract_text(p)
            if not raw.strip():
                continue
            for idx, c in enumerate(
                chunk_text_by_strategy(
                    raw,
                    strategy="fixed",
                    chunk_size=self.cfg.chunk.chunk_size,
                    chunk_overlap=self.cfg.chunk.chunk_overlap,
                )
            ):
                chunk_id = f"{p.name}:{idx}:{uuid.uuid4().hex[:8]}"
                texts.append(c)
                metas.append(
                    {
                        "doc_name": p.name,
                        "doc_path": str(p),
                        "chunk_id": chunk_id,
                        "kb_id": self.cfg.id,
                    }
                )

        if not texts:
            return

        emb_model_name = self.cfg.embedding_model_name
        vectors = self._model_manager.call_embedding(
            EmbeddingRequest(texts=texts, metadata={"request_id": request_id}), model_name=emb_model_name
        ).vectors
        for text, vec, meta in zip(texts, vectors, metas, strict=False):
            chunks.append(EmbeddedChunk(chunk_id=meta["chunk_id"], text=text, vector=list(vec), meta=meta))

        self._vector_store.add_embedded_chunks(chunks)

    def search(
        self,
        *,
        query: str,
        request_id: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        need_citation: bool | None = None,
    ) -> dict[str, Any]:
        """
        将 `query` 向量化后在 Chroma 中做相似检索。

        返回：`{ "contexts": [{text, source?, score}], "query", "request_id" }`；
        `filters` 为 metadata 等值过滤；`need_citation` 控制是否附带文档引用字段。
        """
        top_k = int(top_k or self.cfg.retrieval.top_k)
        filters = filters or {}
        need_citation = bool(need_citation if need_citation is not None else self.cfg.retrieval.need_citation)
        emb_model_name = self.cfg.embedding_model_name
        qvec = self._model_manager.call_embedding(
            EmbeddingRequest(texts=[query], metadata={"request_id": request_id}), model_name=emb_model_name
        ).vectors[0]
        results = self._vector_store.query_similar_chunks(
            qvec,
            top_k=top_k,
            candidate_k=self.cfg.retrieval.candidate_k,
            min_score=self.cfg.retrieval.min_score,
            filters=filters,
        )
        contexts = []
        for score, chunk in results:
            source = {
                "doc_id": chunk.meta.get("kb_id"),
                "doc_name": chunk.meta.get("doc_name"),
                "chunk_id": chunk.meta.get("chunk_id"),
            }
            contexts.append({"text": chunk.text, "source": source if need_citation else None, "score": score})
        return {"contexts": contexts, "query": query, "request_id": request_id}

"""
SIA_agent.rag.chroma_vector_store - Chroma 向量存储封装

提供知识库的向量存储与检索能力：
- upsert()：写入分块（含 text / embedding / metadata）
- retrieve()：向量相似度检索，支持 metadata 等值过滤
- get_chunk_count()：当前分块数量
- clear()：清空整个知识库的向量数据

技术细节：
- collection 命名：kb_id 清洗为 Chroma 合法的 collection 名
- chunk_id 映射：业务 chunk_id 可能含特殊字符，映射为 SHA256 前缀
- metadata 约束：Chroma metadata 仅支持标量，复杂类型统一转字符串
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import chromadb

from .embedded_chunk import EmbeddedChunk
from .vector_similarity import chroma_cosine_distance_to_similarity


def _collection_name(kb_id: str) -> str:
    """将知识库 id 清洗为 Chroma 允许的 collection 名称。"""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", kb_id).strip("_")
    return (s or "kb_default")[:60]


def _stable_chroma_id(chunk_id: str) -> str:
    """业务 chunk_id 可能含特殊字符，映射为 Chroma 安全的短 id。"""
    return hashlib.sha256(chunk_id.encode("utf-8")).hexdigest()[:48]


def _flatten_metadata_for_chroma(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma metadata 仅支持标量；其余类型转为字符串。"""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


def _filters_to_chroma_where(filters: dict[str, Any]) -> dict[str, Any] | None:
    """将等值过滤 dict 转为 Chroma `where` 表达式（单条件或 `$and`）。"""
    if not filters:
        return None
    parts: list[dict[str, Any]] = []
    for k, v in filters.items():
        if v is None:
            continue
        parts.append({str(k): v})
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


class ChromaVectorStore:
    """
    使用 Chroma 持久化客户端的向量库：每个知识库对应一个 collection。
    `persist_dir` 为 Chroma 根目录（勿与旧版手写 JSON 索引混用）。
    """

    def __init__(self, *, persist_dir: Path, kb_id: str) -> None:
        """在 `persist_dir` 下创建/打开持久化客户端，并 `get_or_create` 本知识库的 collection。"""
        self._persist_dir = Path(persist_dir)
        self._name = _collection_name(kb_id)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self._name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def chunk_count(self) -> int:
        """当前 collection 中向量条数。"""
        return int(self._collection.count())

    def reset(self) -> None:
        """删除并重建本知识库的 collection（用于全量重建索引）。"""
        try:
            self._client.delete_collection(self._name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self._name,
            metadata={"hnsw:space": "cosine"},
        )

    def delete_by_filters(self, filters: dict[str, Any]) -> int:
        """按 metadata 等值过滤删除（用于同名文件重新入库时清理旧分片）。"""
        where = _filters_to_chroma_where(filters or {})
        if not where:
            return 0
        # chroma delete() 返回 None；这里尽最大努力返回删除条数
        before = int(self._collection.count())
        try:
            self._collection.delete(where=where)
        except Exception:
            return 0
        after = int(self._collection.count())
        return max(0, before - after)

    def count_by_filters(self, filters: dict[str, Any]) -> int:
        """按 metadata 等值过滤统计条数。"""
        where = _filters_to_chroma_where(filters or {})
        if not where:
            return int(self._collection.count())
        try:
            got = self._collection.get(where=where, include=[])
            ids = got.get("ids") or []
            return int(len(ids))
        except Exception:
            return 0

    def update_metadata_for_filters(
        self,
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> int:
        """按 metadata 等值过滤批量更新字段（不改动向量与正文）。"""
        where = _filters_to_chroma_where(filters or {})
        if not where or not updates:
            return 0
        flat_updates = _flatten_metadata_for_chroma(updates)
        if not flat_updates:
            return 0
        try:
            got = self._collection.get(where=where, include=["metadatas"])
            ids = got.get("ids") or []
            metas = got.get("metadatas") or []
            if not ids:
                return 0
            new_metas: list[dict[str, Any]] = []
            for meta in metas:
                base = dict(meta or {})
                base.update(flat_updates)
                new_metas.append(_flatten_metadata_for_chroma(base))
            self._collection.update(ids=ids, metadatas=new_metas)
            return len(ids)
        except Exception:
            return 0

    def export_embedded_chunks_by_filters(self, filters: dict[str, Any]) -> list[EmbeddedChunk]:
        """按 metadata 等值过滤导出完整分片（含向量），用于入库失败回滚。"""
        where = _filters_to_chroma_where(filters or {})
        if not where:
            return []
        out: list[EmbeddedChunk] = []
        batch = 500
        offset = 0
        while True:
            got = self._collection.get(
                where=where,
                include=["documents", "metadatas", "embeddings"],
                limit=batch,
                offset=offset,
            )
            ids = got.get("ids") or []
            if not ids:
                break
            documents = got.get("documents") or []
            metadatas = got.get("metadatas") or []
            embeddings = got.get("embeddings") or []
            for i, _cid in enumerate(ids):
                meta = dict(metadatas[i] if i < len(metadatas) and metadatas[i] else {})
                text = documents[i] if i < len(documents) and documents[i] is not None else ""
                raw_vec = embeddings[i] if i < len(embeddings) and embeddings[i] is not None else []
                chunk_id = str(meta.get("chunk_id") or _cid)
                out.append(
                    EmbeddedChunk(
                        chunk_id=chunk_id,
                        text=text,
                        vector=[float(x) for x in raw_vec],
                        meta=meta,
                    )
                )
            if len(ids) < batch:
                break
            offset += len(ids)
        return out

    def list_distinct_documents(self) -> list[dict[str, Any]]:
        """
        按 ``metadata.doc_id`` 聚合当前 collection 中的逻辑文档。

        返回每项含 ``doc_id``、``source``（入库文件名）、``format``、``kb_id``、``chunk_count``；
        若入库时携带 ``document`` 库主键，则另有 ``source_doc_id``。
        大库分页拉取 metadata，避免一次性加载全部向量。
        """
        n = int(self._collection.count())
        if n <= 0:
            return []

        acc: dict[str, dict[str, Any]] = {}
        batch = 2000
        offset = 0
        while offset < n:
            res = self._collection.get(
                include=["metadatas"],
                limit=batch,
                offset=offset,
            )
            metas = res.get("metadatas") or []
            if not metas:
                break
            for meta in metas:
                if not meta:
                    continue
                did = str(meta.get("doc_id") or "").strip()
                if not did:
                    continue
                row = acc.get(did)
                if row is None:
                    acc[did] = {
                        "doc_id": did,
                        "source": str(meta.get("source") or ""),
                        "format": str(meta.get("format") or ""),
                        "kb_id": str(meta.get("kb_id") or ""),
                        "chunk_count": 0,
                        "source_doc_id": str(meta.get("source_doc_id") or ""),
                    }
                    row = acc[did]
                row["chunk_count"] = int(row["chunk_count"]) + 1
                if not row.get("source") and meta.get("source"):
                    row["source"] = str(meta.get("source"))
                if not row.get("format") and meta.get("format"):
                    row["format"] = str(meta.get("format"))
                if not row.get("kb_id") and meta.get("kb_id"):
                    row["kb_id"] = str(meta.get("kb_id"))
                if not row.get("source_doc_id") and meta.get("source_doc_id"):
                    row["source_doc_id"] = str(meta.get("source_doc_id"))
            offset += len(metas)
            if len(metas) < batch:
                break

        out = list(acc.values())
        for r in out:
            if not str(r.get("source_doc_id") or "").strip():
                r.pop("source_doc_id", None)
        out.sort(key=lambda r: (str(r.get("source") or ""), str(r.get("doc_id") or "")))
        return out

    def add_embedded_chunks(self, chunks: list[EmbeddedChunk], *, batch_size: int = 128) -> None:
        """分批写入向量、正文与 metadata。"""
        if not chunks:
            return
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            ids = [_stable_chroma_id(c.chunk_id) for c in batch]
            embeddings = [list(map(float, c.vector)) for c in batch]
            documents = [c.text for c in batch]
            metadatas = [_flatten_metadata_for_chroma(c.meta) for c in batch]
            self._collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def query_similar_chunks(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        candidate_k: int = 15,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[float, EmbeddedChunk]]:
        """
        用查询向量检索最相近的分块。

        返回 `(相似度分数, EmbeddedChunk)` 列表，长度不超过 `top_k`；
        `min_score` 在向量分数映射后做下限过滤。
        """
        filters = filters or {}
        n_fetch = max(int(top_k), int(candidate_k), 1)
        where = _filters_to_chroma_where(filters)
        qv = [list(map(float, query_vector))]
        res = self._collection.query(
            query_embeddings=qv,
            n_results=n_fetch,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0] or []
        documents = (res.get("documents") or [[]])[0] or []
        metadatas = (res.get("metadatas") or [[]])[0] or []
        distances = (res.get("distances") or [[]])[0] or []

        out: list[tuple[float, EmbeddedChunk]] = []
        for i, _cid in enumerate(ids):
            dist = float(distances[i]) if i < len(distances) else 0.0
            score = chroma_cosine_distance_to_similarity(dist)
            if min_score is not None and score < float(min_score):
                continue
            meta = dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {}
            text = documents[i] if i < len(documents) and documents[i] is not None else ""
            chunk_id = str(meta.get("chunk_id") or _cid)
            chunk = EmbeddedChunk(chunk_id=chunk_id, text=text, vector=[], meta=meta)
            out.append((score, chunk))
            if len(out) >= int(top_k):
                break
        return out

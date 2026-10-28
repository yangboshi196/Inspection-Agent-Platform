"""Milvus 向量存储。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from agent_base.rag.embedded_chunk import EmbeddedChunk
from agent_base.rag.vector_similarity import score_query_against_stored_vector

try:
    from pymilvus import DataType, MilvusClient
except ImportError:  # pragma: no cover
    DataType = None  # type: ignore[misc, assignment]
    MilvusClient = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)
_ID_MAX_LENGTH = 64


def _collection_name(kb_id: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", kb_id).strip("_")
    return (s or "kb_default")[:60]


def _stable_id(chunk_id: str) -> str:
    return hashlib.sha256(chunk_id.encode("utf-8")).hexdigest()[:48]


def _flatten_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


def _match_filters(meta: dict[str, Any], filters: dict[str, Any]) -> bool:
    for k, v in filters.items():
        if v is None:
            continue
        if str(meta.get(k)) != str(v):
            return False
    return True


def _coerce_vector_list(raw: Any) -> list[float]:
    """将 Milvus / NumPy 向量安全转为 Python float 列表（避免 ndarray 布尔判断异常）。"""
    if raw is None:
        return []
    try:
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
    except Exception:
        pass
    if isinstance(raw, list):
        return [float(x) for x in raw]
    try:
        return [float(x) for x in raw]
    except TypeError:
        return []


class MilvusVectorStore:
    """Milvus 向量库：每个 kb_id 对应一个 collection。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        kb_id: str,
        persist_dir: Path | None = None,
        dim: int | None = None,
    ) -> None:
        if MilvusClient is None:
            raise RuntimeError("pymilvus 未安装，请 pip install pymilvus")
        self._name = _collection_name(kb_id)
        self._dim = dim
        uri = f"http://{host}:{port}"
        if persist_dir is not None:
            persist_dir.mkdir(parents=True, exist_ok=True)
        connect_timeout = float(os.environ.get("MILVUS_CONNECT_TIMEOUT", "3"))
        self._client = MilvusClient(uri=uri, timeout=connect_timeout)
        self._ensure_collection()

    def _resolve_dim(self) -> int:
        if self._dim is not None:
            return int(self._dim)
        try:
            from inspection_platform.embedding.backend import embedding_dimension

            self._dim = embedding_dimension()
        except Exception:
            self._dim = 1024
        return int(self._dim)

    def _describe_schema(self) -> tuple[bool, int | None]:
        """返回 (id 是否为字符串, 向量维度)。"""
        try:
            desc = self._client.describe_collection(self._name)
        except Exception:
            return False, None
        id_is_string = False
        vector_dim: int | None = None
        for field in desc.get("fields") or []:
            if field.get("is_primary"):
                ftype = field.get("type")
                if DataType is not None and ftype == DataType.VARCHAR:
                    id_is_string = True
                elif str(ftype).endswith("VARCHAR") or ftype == 21:
                    id_is_string = True
            if field.get("name") == "vector":
                params = field.get("params") or {}
                dim = params.get("dim")
                if dim is not None:
                    vector_dim = int(dim)
        return id_is_string, vector_dim

    def _drop_collection_if_needed(self) -> None:
        if not self._client.has_collection(self._name):
            return
        dim = self._resolve_dim()
        id_is_string, vector_dim = self._describe_schema()
        if id_is_string and vector_dim == dim:
            return
        logger.warning(
            "Milvus collection %s schema 不兼容（id_string=%s vector_dim=%s expected_dim=%s），将重建",
            self._name,
            id_is_string,
            vector_dim,
            dim,
        )
        self._client.drop_collection(self._name)

    def _create_collection(self) -> None:
        dim = self._resolve_dim()
        try:
            from pymilvus.milvus_client.index import IndexParams

            index_params = IndexParams()
            index_params.add_index(
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            self._client.create_collection(
                collection_name=self._name,
                dimension=dim,
                metric_type="COSINE",
                auto_id=False,
                primary_field_name="id",
                id_type="string",
                max_length=_ID_MAX_LENGTH,
                vector_field_name="vector",
                index_params=index_params,
            )
        except Exception:
            self._client.create_collection(
                collection_name=self._name,
                dimension=dim,
                metric_type="COSINE",
                auto_id=False,
                primary_field_name="id",
                id_type="string",
                max_length=_ID_MAX_LENGTH,
                vector_field_name="vector",
            )

    def _ensure_collection(self) -> None:
        self._drop_collection_if_needed()
        if self._client.has_collection(self._name):
            return
        self._create_collection()

    def _ensure_dim(self, vector: list[float]) -> None:
        vec = _coerce_vector_list(vector)
        if vec:
            self._dim = len(vec)
        if not self._client.has_collection(self._name):
            self._ensure_collection()

    @property
    def chunk_count(self) -> int:
        try:
            stats = self._client.get_collection_stats(self._name)
            return int(stats.get("row_count", 0))
        except Exception:
            return 0

    def reset(self) -> None:
        if self._client.has_collection(self._name):
            self._client.drop_collection(self._name)
        self._ensure_collection()

    def delete_by_filters(self, filters: dict[str, Any]) -> int:
        if not filters:
            return 0
        rows = self._client.query(
            collection_name=self._name,
            filter="",
            output_fields=["id", "meta_json"],
            limit=16384,
        )
        ids = [
            str(r["id"])
            for r in rows
            if _match_filters(json.loads(str(r.get("meta_json") or "{}")), filters)
        ]
        if not ids:
            return 0
        self._client.delete(collection_name=self._name, ids=ids)
        try:
            self._client.flush(self._name)
        except Exception:
            pass
        return len(ids)

    def count_by_filters(self, filters: dict[str, Any]) -> int:
        if not filters:
            return self.chunk_count
        rows = self._client.query(
            collection_name=self._name,
            filter="",
            output_fields=["meta_json"],
            limit=16384,
        )
        return sum(
            1
            for r in rows
            if _match_filters(json.loads(str(r.get("meta_json") or "{}")), filters)
        )

    def update_metadata_for_filters(
        self,
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> int:
        if not filters or not updates:
            return 0
        rows = self._client.query(
            collection_name=self._name,
            filter="",
            output_fields=["id", "text", "vector", "meta_json"],
            limit=16384,
        )
        flat_updates = _flatten_metadata(updates)
        upsert_rows: list[dict[str, Any]] = []
        for row in rows:
            meta = json.loads(str(row.get("meta_json") or "{}"))
            if not _match_filters(meta, filters):
                continue
            meta.update(flat_updates)
            upsert_rows.append(
                {
                    "id": row["id"],
                    "text": row.get("text") or "",
                    "vector": _coerce_vector_list(row.get("vector")),
                    "meta_json": json.dumps(meta, ensure_ascii=False),
                }
            )
        if upsert_rows:
            self._client.upsert(collection_name=self._name, data=upsert_rows)
        return len(upsert_rows)

    def export_embedded_chunks_by_filters(self, filters: dict[str, Any]) -> list[EmbeddedChunk]:
        rows = self._client.query(
            collection_name=self._name,
            filter="",
            output_fields=["id", "text", "vector", "meta_json"],
            limit=16384,
        )
        out: list[EmbeddedChunk] = []
        for row in rows:
            meta = json.loads(str(row.get("meta_json") or "{}"))
            if filters and not _match_filters(meta, filters):
                continue
            chunk_id = str(meta.get("chunk_id") or row["id"])
            vec = _coerce_vector_list(row.get("vector"))
            out.append(
                EmbeddedChunk(
                    chunk_id=chunk_id,
                    text=str(row.get("text") or ""),
                    vector=vec,
                    meta=meta,
                )
            )
        return out

    def list_distinct_documents(self) -> list[dict[str, Any]]:
        rows = self._client.query(
            collection_name=self._name,
            filter="",
            output_fields=["meta_json"],
            limit=16384,
        )
        acc: dict[str, dict[str, Any]] = {}
        for row in rows:
            meta = json.loads(str(row.get("meta_json") or "{}"))
            did = str(meta.get("doc_id") or "").strip()
            if not did:
                continue
            item = acc.get(did)
            if item is None:
                acc[did] = {
                    "doc_id": did,
                    "source": str(meta.get("source") or ""),
                    "format": str(meta.get("format") or ""),
                    "kb_id": str(meta.get("kb_id") or ""),
                    "chunk_count": 0,
                    "source_doc_id": str(meta.get("source_doc_id") or ""),
                }
                item = acc[did]
            item["chunk_count"] = int(item["chunk_count"]) + 1
        out = list(acc.values())
        for r in out:
            if not str(r.get("source_doc_id") or "").strip():
                r.pop("source_doc_id", None)
        out.sort(key=lambda r: (str(r.get("source") or ""), str(r.get("doc_id") or "")))
        return out

    def add_embedded_chunks(self, chunks: list[EmbeddedChunk], *, batch_size: int = 128) -> None:
        if not chunks:
            return
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            if batch:
                self._ensure_dim(list(map(float, batch[0].vector)))
            rows: list[dict[str, Any]] = []
            for c in batch:
                meta = _flatten_metadata(c.meta)
                rows.append(
                    {
                        "id": _stable_id(c.chunk_id),
                        "text": c.text,
                        "vector": [float(x) for x in c.vector],
                        "meta_json": json.dumps({**meta, "chunk_id": c.chunk_id}, ensure_ascii=False),
                    }
                )
            self._client.upsert(collection_name=self._name, data=rows)
        try:
            self._client.flush(self._name)
        except Exception:
            pass

    def query_similar_chunks(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        candidate_k: int = 15,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[float, EmbeddedChunk]]:
        filters = filters or {}
        n_fetch = max(int(top_k), int(candidate_k), 1)
        self._ensure_dim(query_vector)
        res = self._client.search(
            collection_name=self._name,
            data=[list(map(float, query_vector))],
            limit=n_fetch,
            output_fields=["text", "meta_json", "vector"],
        )
        hits = res[0] if res else []
        qv = list(map(float, query_vector))
        out: list[tuple[float, EmbeddedChunk]] = []
        for hit in hits:
            dist_raw = float(hit.get("distance", 0.0))
            entity = hit.get("entity") or {}
            stored = entity.get("vector")
            stored_vec = (
                list(map(float, stored))
                if isinstance(stored, (list, tuple)) and stored
                else None
            )
            score = score_query_against_stored_vector(
                qv,
                stored_vec,
                milvus_raw=dist_raw,
            )
            if min_score is not None and score < float(min_score):
                continue
            meta = json.loads(str(entity.get("meta_json") or "{}"))
            if filters and not _match_filters(meta, filters):
                continue
            chunk_id = str(meta.get("chunk_id") or hit.get("id"))
            chunk = EmbeddedChunk(
                chunk_id=chunk_id,
                text=str(entity.get("text") or ""),
                vector=stored_vec or [],
                meta=meta,
            )
            out.append((score, chunk))
            if len(out) >= top_k:
                break
        return out

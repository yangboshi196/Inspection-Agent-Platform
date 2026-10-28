"""多格式文档向量化入库（Milvus + ``ModelManager`` 嵌入，与 Agent 同源）。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent_base.model_manager.manager import ModelManager
from inspection_platform.deps import platform_embed_texts
from inspection_platform.app.vector import create_vector_store, list_vector_collections

from .ingest_pipeline import run_ingest_pipeline


def _doc_id(kb_id: str, source_name: str) -> str:
    h = hashlib.sha256(f"{kb_id}\0{source_name}".encode("utf-8")).hexdigest()
    return h[:32]


def _normalize_sqlite_document_id(raw: str) -> str:
    """
    将 ``document`` 表主键规范为与 SQLite 一致、且可作 Milvus ``doc_id`` 的字符串。

    - 支持 ``uuid4().hex`` 形式（32 位十六进制）。
    - 支持带连字符的 UUID 字符串，会去掉连字符并转小写，与 ``uuid4().hex`` 对齐。
    - 禁止 ``:``（否则无法安全拼 ``chunk_id = f"{doc_id}:{i}"``）。
    """
    s = raw.strip()
    if not s:
        raise ValueError("source_doc_id 不能为空")
    if ":" in s:
        raise ValueError("document id 不能包含字符 ':'")
    um = re.fullmatch(
        r"([0-9a-fA-F]{8})-([0-9a-fA-F]{4})-([0-9a-fA-F]{4})-([0-9a-fA-F]{4})-([0-9a-fA-F]{12})",
        s,
    )
    if um:
        s = "".join(um.groups()).lower()
    else:
        s = s.lower()
    if len(s) > 128 or len(s) < 1:
        raise ValueError("document id 长度须在 1～128 之间")
    if not re.fullmatch(r"[0-9a-f]{32}", s) and not re.fullmatch(r"[0-9a-z_-]{1,128}", s):
        raise ValueError(
            "document id 须为 32 位十六进制（与 uuid4().hex 一致），"
            "或仅含字母、数字、下划线、连字符"
        )
    return s


def _vector_doc_id(
    kb: str,
    filename: str,
    *,
    source_doc_id: str | None,
) -> tuple[str, str | None]:
    """
    返回 (Milvus 逻辑 doc_id, SQLite 文档主键或 None)。

    若传入 ``source_doc_id``，则 **Milvus 的 doc_id 与 SQLite 主键相同**（经规范化），
    并写入每条分片的 ``metadata.doc_id`` 与 ``metadata.source_doc_id``。
    未传入时仍按 ``kb_id`` + 文件名生成哈希 doc_id（无库绑定）。
    """
    raw = (source_doc_id or "").strip()
    if not raw:
        return _doc_id(kb, filename), None
    normalized = _normalize_sqlite_document_id(raw)
    return normalized, normalized


class KnowledgeIngestService:
    def __init__(
        self,
        model_manager: ModelManager,
        *,
        embedding_model_name: str | None = None,
    ) -> None:
        self._mm = model_manager
        self._emb_name = embedding_model_name

    def _store(self, kb_id: str):
        kb = (kb_id or "default").strip() or "default"
        return create_vector_store(kb_id=kb)

    def ingest_file(
        self,
        *,
        filename: str,
        content: bytes,
        kb_id: str = "default",
        replace_existing: bool = True,
        max_chars: int = 900,
        overlap: int = 120,
        source_doc_id: str | None = None,
    ) -> dict[str, Any]:
        kb = (kb_id or "default").strip() or "default"
        store = create_vector_store(kb_id=kb)
        doc_id, library_sid = _vector_doc_id(kb, filename, source_doc_id=source_doc_id)
        _state, out = run_ingest_pipeline(
            store=store,
            mm=self._mm,
            embedding_model_name=self._emb_name,
            filename=filename,
            content=content,
            kb_id=kb,
            doc_id=doc_id,
            library_sid=library_sid,
            replace_existing=replace_existing,
            max_chars=max_chars,
            overlap=overlap,
        )
        return out

    def ingest_from_document(
        self,
        *,
        document_id: str,
        kb_id: str = "default",
        replace_existing: bool = True,
        max_chars: int = 900,
        overlap: int = 120,
    ) -> dict[str, Any]:
        """从文档库 SQLite + 磁盘原文读取并向量化；Milvus doc_id 与 document.id 一致。"""
        from inspection_platform.document.service import DocumentService

        did = document_id.strip()
        if not did:
            raise ValueError("document_id 不能为空")

        doc_svc = DocumentService()
        doc_svc.ensure_ready()
        try:
            rec = doc_svc.get_by_id(did)
        except KeyError as e:
            raise ValueError(f"文档库中不存在 document_id={did!r}") from e

        path = doc_svc.resolve_path(did)
        if not path.is_file():
            raise ValueError(f"文档原文文件缺失：{rec.storage_relpath}")

        content = path.read_bytes()
        filename = rec.name.strip() or path.name
        out = self.ingest_file(
            filename=filename,
            content=content,
            kb_id=kb_id,
            replace_existing=replace_existing,
            max_chars=max_chars,
            overlap=overlap,
            source_doc_id=rec.id,
        )
        out["document_id"] = rec.id
        out["document_name"] = rec.name
        return out

    def delete_document(self, *, kb_id: str, doc_id: str) -> int:
        return self._store(kb_id).delete_by_filters({"doc_id": doc_id.strip()})

    def count_document_chunks(self, *, kb_id: str, doc_id: str) -> int:
        return self._store(kb_id).count_by_filters({"doc_id": doc_id.strip()})

    def list_document_chunks(self, *, kb_id: str, doc_id: str) -> list[dict[str, Any]]:
        """按 chunk_index 升序返回文档全部分片（不做语义检索）。"""
        did = doc_id.strip()
        if not did:
            return []
        rows = self._store(kb_id).export_embedded_chunks_by_filters({"doc_id": did})
        out: list[dict[str, Any]] = []
        for ch in rows:
            meta = dict(ch.meta or {})
            idx = meta.get("chunk_index")
            if idx is None:
                cid = str(meta.get("chunk_id") or ch.chunk_id or "")
                if ":" in cid:
                    try:
                        idx = int(cid.rsplit(":", 1)[-1])
                    except ValueError:
                        idx = 0
                else:
                    idx = 0
            out.append(
                {
                    "chunk_id": str(meta.get("chunk_id") or ch.chunk_id),
                    "chunk_index": int(idx),
                    "text": str(ch.text or ""),
                    "meta": meta,
                }
            )
        out.sort(key=lambda r: (int(r["chunk_index"]), str(r["chunk_id"])))
        return out

    def sync_document_display_name(
        self,
        *,
        document_id: str,
        document_name: str,
        kb_id: str = "default",
    ) -> int:
        """更新向量分片 metadata.source / document_name，不重新向量化。"""
        did = document_id.strip()
        name = document_name.strip()
        if not did or not name:
            return 0
        return self._store(kb_id).update_metadata_for_filters(
            {"doc_id": did},
            {"source": name, "document_name": name},
        )

    def sync_document_display_name_all_partitions(
        self,
        *,
        document_id: str,
        document_name: str,
    ) -> int:
        """在所有知识库 collection 中更新该 doc_id 分片的展示名，不重新向量化。"""
        did = document_id.strip()
        name = document_name.strip()
        if not did or not name:
            return 0
        total = 0
        for coll in list_vector_collections():
            if coll == "spec_rules":
                continue
            total += create_vector_store(kb_id=coll).update_metadata_for_filters(
                {"doc_id": did},
                {"source": name, "document_name": name},
            )
        return total

    def delete_document_all_partitions(self, doc_id: str) -> int:
        """在所有知识库 collection 中删除该 doc_id 的分片（不影响 spec_rules 与已发布规范）。"""
        did = doc_id.strip()
        if not did:
            return 0
        collections = list_vector_collections()
        if "default" not in collections:
            collections = ["default", *collections]
        total = 0
        seen: set[str] = set()
        for coll in collections:
            if coll in seen or coll == "spec_rules":
                continue
            seen.add(coll)
            total += create_vector_store(kb_id=coll).delete_by_filters({"doc_id": did})
        return total

    def cleanup_orphan_chunks(self) -> dict[str, Any]:
        """删除向量库中 doc_id 不在文档库 MySQL 的孤儿分片（仅知识库分区）。"""
        from inspection_platform.document.db import get_connection as doc_conn

        conn = doc_conn()
        try:
            rows = conn.execute("SELECT id FROM document").fetchall()
            valid_ids = {str(r["id"]) for r in rows}
        finally:
            conn.close()

        deleted = 0
        collections_scanned = 0
        for coll in list_vector_collections():
            if coll == "spec_rules":
                continue
            collections_scanned += 1
            store = create_vector_store(kb_id=coll)
            rows = store.export_embedded_chunks_by_filters({})
            orphan_doc_ids = {
                str(c.meta.get("doc_id") or "")
                for c in rows
                if str(c.meta.get("doc_id") or "") and str(c.meta.get("doc_id") or "") not in valid_ids
            }
            for od in orphan_doc_ids:
                deleted += store.delete_by_filters({"doc_id": od})
        return {
            "collections_scanned": collections_scanned,
            "chunks_deleted": deleted,
        }

    def stats(self, kb_id: str) -> dict[str, Any]:
        store = self._store(kb_id)
        return {"kb_id": kb_id, "chunk_count": store.chunk_count}

    def list_documents(self, kb_id: str) -> list[dict[str, Any]]:
        """列出当前知识库 Milvus 中已入库的逻辑文档（按 doc_id 聚合）。"""
        kb = (kb_id or "default").strip() or "default"
        store = create_vector_store(kb_id=kb)
        return store.list_distinct_documents()

    def query(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            raise ValueError("query is empty")
        store = self._store(kb_id)
        try:
            qv = platform_embed_texts(
                [q],
                model_name=self._emb_name,
                metadata={"stage": "knowledge_query", "kb_id": kb_id},
            )[0]
        except Exception as e:
            raise ValueError(
                "查询向量化失败：请检查 embedding 服务是否可用。"
                f" 详情：{e}"
            ) from e
        pairs = store.query_similar_chunks(list(map(float, qv)), top_k=top_k, filters=filters)
        out: list[dict[str, Any]] = []
        for score, ch in pairs:
            out.append(
                {
                    "score": score,
                    "text": ch.text,
                    "meta": ch.meta,
                }
            )
        return out

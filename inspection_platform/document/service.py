"""文档：5 列元数据（SQLite）+ 原文磁盘。

环境变量::

    SIA_DOC_FILES_ROOT  (DOCUMENT_FILES_ROOT, DOCUMENTS_FILES_ROOT)
"""

from __future__ import annotations

import mimetypes
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inspection_platform.envutil import env_first

from .db import db_path, get_connection
from .errors import DocumentInUseError


def _files_root() -> Path:
    env = env_first(
        "SIA_DOC_FILES_ROOT",
        "DOCUMENT_FILES_ROOT",
        "DOCUMENTS_FILES_ROOT",
    )
    if env:
        return Path(env).expanduser().resolve()
    return (db_path().parent / "files").resolve()


def _safe_extension(original_filename: str) -> str:
    ext = Path(original_filename).suffix.lower()
    if not ext or len(ext) > 16:
        return ".bin"
    body = ext[1:]
    if body and all(c.isalnum() or c in "-_" for c in body):
        return ext
    return ".bin"


@dataclass
class DocumentRecord:
    id: str
    doc_type: str
    name: str
    storage_relpath: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_type": self.doc_type,
            "name": self.name,
            "storage_relpath": self.storage_relpath,
            "created_at": self.created_at,
        }


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        id=str(row["id"]),
        doc_type=str(row["doc_type"]),
        name=str(row["name"]),
        storage_relpath=str(row["storage_relpath"]),
        created_at=str(row["created_at"]),
    )


class DocumentService:
    """id / doc_type / name / storage_relpath / created_at。"""

    def __init__(self, *, max_upload_bytes: int = 50 * 1024 * 1024) -> None:
        self._max_upload_bytes = max_upload_bytes

    def ensure_ready(self) -> None:
        """文档 SQLite 在 lifespan init_region_db/启动流程中初始化；此处仅确保文件目录存在。"""
        _files_root().mkdir(parents=True, exist_ok=True)

    def store(
        self,
        *,
        file_content: bytes,
        original_filename: str,
        doc_type: str,
        name: str | None,
    ) -> dict[str, Any]:
        dt = doc_type.strip()
        if not dt:
            raise ValueError("doc_type is required")
        if len(dt) > 256:
            raise ValueError("doc_type too long (max 256)")
        if len(file_content) > self._max_upload_bytes:
            raise ValueError(f"file exceeds max size ({self._max_upload_bytes} bytes)")
        fname = original_filename.strip()
        if not fname:
            raise ValueError("original_filename is required")

        display_name = (name or "").strip() or Path(fname).name
        oid = uuid.uuid4().hex
        ext = _safe_extension(fname)
        relpath = f"{oid}/original{ext}"
        root = _files_root()
        doc_dir = root / oid
        final_path = doc_dir / f"original{ext}"
        now = datetime.now(timezone.utc).isoformat()

        doc_dir.mkdir(parents=True, exist_ok=True)
        tmp = doc_dir / f".{oid}.tmp"
        try:
            tmp.write_bytes(file_content)
            tmp.replace(final_path)
        except Exception:
            if doc_dir.exists():
                shutil.rmtree(doc_dir, ignore_errors=True)
            raise

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO document (
                    id, doc_type, name, storage_relpath, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    oid,
                    dt,
                    display_name,
                    relpath.replace("\\", "/"),
                    now,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            if doc_dir.exists():
                shutil.rmtree(doc_dir, ignore_errors=True)
            raise
        finally:
            conn.close()

        return self._record_to_api(self.get_by_id(oid))

    def get_by_id(self, doc_id: str) -> DocumentRecord:
        conn = get_connection()
        try:
            cur = conn.execute("SELECT * FROM document WHERE id = ?", (doc_id.strip(),))
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(doc_id)
        return _row_to_record(row)

    def resolve_path(self, doc_id: str) -> Path:
        rec = self.get_by_id(doc_id)
        return (_files_root() / rec.storage_relpath).resolve()

    def file_stats(self, doc_id: str) -> dict[str, Any]:
        """读取磁盘原文大小；PDF 可选返回页数。"""
        return self._file_stats_for_record(self.get_by_id(doc_id))

    def _file_stats_for_record(self, rec: DocumentRecord) -> dict[str, Any]:
        path = (_files_root() / rec.storage_relpath).resolve()
        if not path.is_file():
            return {"file_size_bytes": 0, "page_count": None}
        size = int(path.stat().st_size)
        page_count: int | None = None
        if path.suffix.lower() == ".pdf":
            try:
                import io

                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(path.read_bytes()))
                page_count = len(reader.pages)
            except Exception:
                page_count = None
        return {"file_size_bytes": size, "page_count": page_count}

    def _record_to_api(self, rec: DocumentRecord, *, include_stats: bool = True) -> dict[str, Any]:
        out = rec.as_dict()
        if include_stats:
            out.update(self.file_stats(rec.id))
        return out

    def guess_media_type(self, doc_id: str) -> str:
        rec = self.get_by_id(doc_id)
        guessed, _ = mimetypes.guess_type(rec.name)
        return guessed or "application/octet-stream"

    def list_document(
        self,
        *,
        doc_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        brief: bool = True,
    ) -> list[dict[str, Any]]:
        """列出文档。``brief=True`` 时仅返回列表浏览常用字段（不含磁盘相对路径）。"""
        lim = max(1, min(500, int(limit)))
        off = max(0, int(offset))
        where: list[str] = []
        params: list[Any] = []
        if doc_type is not None:
            where.append("doc_type = ?")
            params.append(doc_type.strip())
        sql = "SELECT * FROM document"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([lim, off])

        conn = get_connection()
        try:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        finally:
            conn.close()
        records = [_row_to_record(r) for r in rows]
        if not brief:
            return [self._record_to_api(r) for r in records]
        out: list[dict[str, Any]] = []
        for rec in records:
            ext = Path(rec.name).suffix.lower() or ""
            if not ext:
                ext = Path(rec.storage_relpath).suffix.lower() or ""
            stats = self._file_stats_for_record(rec)
            out.append(
                {
                    "id": rec.id,
                    "name": rec.name,
                    "doc_type": rec.doc_type,
                    "created_at": rec.created_at,
                    "ext": ext,
                    "file_size_bytes": stats["file_size_bytes"],
                    "page_count": stats.get("page_count"),
                }
            )
        return out

    def delete(self, doc_id: str) -> None:
        rec = self.get_by_id(doc_id)
        from inspection_platform.specification.db import get_connection as spec_conn

        conn_spec = spec_conn()
        try:
            row = conn_spec.execute(
                "SELECT COUNT(*) AS c FROM spec_rule WHERE doc_id = ? AND status = 'published'",
                (rec.id,),
            ).fetchone()
            if row and int(row["c"]) > 0:
                raise DocumentInUseError(rec.id, int(row["c"]))
        finally:
            conn_spec.close()

        from inspection_platform.deps import get_model_manager, platform_embedding_model_name
        from inspection_platform.knowledge.ingest_service import KnowledgeIngestService
        from inspection_platform.specification.service import SpecificationService

        spec = SpecificationService(
            get_model_manager(),
            embedding_model_name=platform_embedding_model_name(),
        )
        spec.delete_draft_rules_for_doc(rec.id)

        ks = KnowledgeIngestService(
            get_model_manager(),
            embedding_model_name=platform_embedding_model_name(),
        )
        ks.delete_document_all_partitions(rec.id)

        conn = get_connection()
        try:
            conn.execute("DELETE FROM document WHERE id = ?", (rec.id,))
            conn.commit()
        finally:
            conn.close()
        doc_dir = _files_root() / rec.id
        if doc_dir.is_dir():
            shutil.rmtree(doc_dir, ignore_errors=True)

    def sync_after_metadata_change(self, doc_id: str, *, new_name: str | None = None) -> dict[str, Any]:
        """文档元数据变更后，同步知识库分片 metadata 与规范 source_trace。"""
        rec = self.get_by_id(doc_id)
        name = (new_name or rec.name).strip()
        from inspection_platform.deps import get_model_manager, platform_embedding_model_name
        from inspection_platform.knowledge.ingest_service import KnowledgeIngestService
        from inspection_platform.specification.service import SpecificationService

        ks = KnowledgeIngestService(
            get_model_manager(),
            embedding_model_name=platform_embedding_model_name(),
        )
        chunks_updated = ks.sync_document_display_name_all_partitions(
            document_id=rec.id,
            document_name=name,
        )
        spec_sync = SpecificationService(
            get_model_manager(),
            embedding_model_name=platform_embedding_model_name(),
        ).sync_document_name(rec.id, name)
        return {
            "document_id": rec.id,
            "document_name": name,
            "knowledge_chunks_updated": chunks_updated,
            **spec_sync,
        }

    def update_metadata(
        self,
        doc_id: str,
        *,
        doc_type: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """更新元数据；至少提供一个要修改的字段。不改动磁盘上的 storage_relpath。"""
        if doc_type is None and name is None:
            raise ValueError("at least one of doc_type, name is required")
        rec = self.get_by_id(doc_id)
        new_dt = doc_type.strip() if doc_type is not None else rec.doc_type
        if not new_dt:
            raise ValueError("doc_type cannot be empty")
        if len(new_dt) > 256:
            raise ValueError("doc_type too long (max 256)")
        if name is not None:
            new_name = name.strip()
            if not new_name:
                raise ValueError("name cannot be empty")
        else:
            new_name = rec.name
        if len(new_name) > 512:
            raise ValueError("name too long (max 512)")

        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE document SET doc_type = ?, name = ?
                WHERE id = ?
                """,
                (new_dt, new_name, rec.id),
            )
            conn.commit()
        finally:
            conn.close()
        out = self._record_to_api(self.get_by_id(rec.id))
        if name is not None and new_name != rec.name:
            sync = self.sync_after_metadata_change(rec.id, new_name=new_name)
            out["sync"] = sync
        return out

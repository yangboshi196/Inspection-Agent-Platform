"""SQLite 连接与表结构初始化。

环境变量::

    SIA_DOC_SQLITE_PATH  (DOCUMENT_DB_PATH, DOCUMENTS_DB_PATH)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from inspection_platform.envutil import env_first

# 元数据 5 列；原文在磁盘 storage_relpath 相对 files/ 目录
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,
    name TEXT NOT NULL,
    storage_relpath TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_doc_type ON document(doc_type);
CREATE INDEX IF NOT EXISTS idx_document_created ON document(created_at DESC);
"""

_TARGET_COLS = frozenset({"id", "doc_type", "name", "storage_relpath", "created_at"})

_LEGACY_DOCUMENT_INDEX_NAMES = (
    "idx_documents_region",
    "idx_documents_doc_type",
    "idx_documents_created",
)

_DOCUMENT_INDEX_NAMES = (
    "idx_document_doc_type",
    "idx_document_created",
)


def _db_path_env() -> str:
    return env_first(
        "SIA_DOC_SQLITE_PATH",
        "DOCUMENT_DB_PATH",
        "DOCUMENTS_DB_PATH",
    )


def _default_db_path() -> Path:
    env = _db_path_env()
    if env:
        return Path(env).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    flat = (repo_root / "data" / "document.db").resolve()
    nested = (repo_root / "data" / "document" / "document.db").resolve()
    old_p = (repo_root / "data" / "documents" / "documents.db").resolve()
    if flat.exists():
        return flat
    if nested.exists():
        return nested
    if old_p.exists():
        return old_p
    return flat


def db_path() -> Path:
    return _default_db_path()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def _table_cols(conn: sqlite3.Connection, name: str) -> set[str]:
    info = conn.execute(f"PRAGMA table_info({name})").fetchall()
    return {str(r[1]) for r in info}


def _drop_document_indexes(conn: sqlite3.Connection) -> None:
    for idx in _LEGACY_DOCUMENT_INDEX_NAMES + _DOCUMENT_INDEX_NAMES:
        conn.execute(f"DROP INDEX IF EXISTS {idx}")


def _ensure_document_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
CREATE INDEX IF NOT EXISTS idx_document_doc_type ON document(doc_type);
CREATE INDEX IF NOT EXISTS idx_document_created ON document(created_at DESC);
""",
    )


def _rename_documents_table_if_needed(conn: sqlite3.Connection) -> None:
    """旧表名 documents → document（索引名一并重建为 idx_document_*）。"""
    if _table_exists(conn, "document"):
        return
    if not _table_exists(conn, "documents"):
        return
    conn.execute("ALTER TABLE documents RENAME TO document")
    for idx in _LEGACY_DOCUMENT_INDEX_NAMES:
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    _ensure_document_indexes(conn)


def _copy_legacy_rows_into_document(conn: sqlite3.Connection, legacy_table: str) -> None:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {legacy_table}").fetchall()
    for row in rows:
        d = {k: row[k] for k in row.keys()}
        doc_type = str(d.get("doc_type") or d.get("source_category") or "company").strip() or "company"
        name = (
            str(d.get("name") or "").strip()
            or str(d.get("title") or "").strip()
            or str(d.get("original_filename") or "").strip()
            or str(d.get("id") or "")
        )
        relp = str(d.get("storage_relpath") or "").strip()
        cid = str(d.get("id") or "").strip()
        cat = str(d.get("created_at") or "").strip()
        if not cid or not relp or not cat or not name:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO document
            (id, doc_type, name, storage_relpath, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cid, doc_type, name, relp.replace("\\", "/"), cat),
        )


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _rename_documents_table_if_needed(conn)

    if not _table_exists(conn, "document"):
        conn.executescript(SCHEMA_SQL)
        return

    cols = _table_cols(conn, "document")
    if cols == _TARGET_COLS:
        _ensure_document_indexes(conn)
        return

    if "region_id" in cols:
        _drop_document_indexes(conn)
        conn.execute("ALTER TABLE document RENAME TO _document_drop_region")
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO document (id, doc_type, name, storage_relpath, created_at)
            SELECT id, doc_type, name, storage_relpath, created_at
            FROM _document_drop_region
            """
        )
        conn.execute("DROP TABLE _document_drop_region")
        _ensure_document_indexes(conn)
        return

    _drop_document_indexes(conn)
    conn.execute("ALTER TABLE document RENAME TO _document_wrong_legacy")
    conn.executescript(SCHEMA_SQL)
    _copy_legacy_rows_into_document(conn, "_document_wrong_legacy")
    conn.execute("DROP TABLE _document_wrong_legacy")
    _ensure_document_indexes(conn)


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()

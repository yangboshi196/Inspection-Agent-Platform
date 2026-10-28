"""规范信息库 SQLite（仅规则元数据；原文与向量走文档库 + /api/knowledge）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import spec_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS spec_rule (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'common',
    requirements TEXT NOT NULL DEFAULT '',
    doc_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    recommended_algorithms_json TEXT NOT NULL DEFAULT '[]',
    algorithm_reasoning TEXT NOT NULL DEFAULT '',
    source_trace_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spec_rule_status ON spec_rule(status);
CREATE INDEX IF NOT EXISTS idx_spec_rule_doc ON spec_rule(doc_id);
"""


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def _table_cols(conn: sqlite3.Connection, name: str) -> set[str]:
    info = conn.execute(f"PRAGMA table_info({name})").fetchall()
    return {str(r[1]) for r in info}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def _migrate_spec_rule_drop_region(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "spec_rule"):
        return
    cols = _table_cols(conn, "spec_rule")
    if "region_id" not in cols:
        return
    conn.execute("DROP INDEX IF EXISTS idx_spec_rule_region")
    conn.execute("DROP INDEX IF EXISTS idx_spec_rule_region_status")
    conn.execute(
        """
        CREATE TABLE spec_rule_new (
            rule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            desc TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT 'common',
            requirements TEXT NOT NULL DEFAULT '',
            doc_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            recommended_algorithms_json TEXT NOT NULL DEFAULT '[]',
            algorithm_reasoning TEXT NOT NULL DEFAULT '',
            source_trace_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO spec_rule_new (
            rule_id, name, desc, source, level, requirements, doc_id, status,
            recommended_algorithms_json, algorithm_reasoning, source_trace_json,
            created_at, updated_at
        )
        SELECT
            rule_id, name, desc, source, level, requirements, doc_id, status,
            COALESCE(recommended_algorithms_json, '[]'),
            COALESCE(algorithm_reasoning, ''),
            '{}',
            created_at, updated_at
        FROM spec_rule
        """
    )
    conn.execute("DROP TABLE spec_rule")
    conn.execute("ALTER TABLE spec_rule_new RENAME TO spec_rule")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spec_rule_status ON spec_rule(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spec_rule_doc ON spec_rule(doc_id)")


def _migrate_spec_rule_columns(conn: sqlite3.Connection) -> None:
    cols = _table_cols(conn, "spec_rule")
    if "recommended_algorithms_json" not in cols:
        conn.execute(
            "ALTER TABLE spec_rule ADD COLUMN recommended_algorithms_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "algorithm_reasoning" not in cols:
        conn.execute(
            "ALTER TABLE spec_rule ADD COLUMN algorithm_reasoning TEXT NOT NULL DEFAULT ''"
        )
    cols = _table_cols(conn, "spec_rule")
    if "recommended_regions_json" not in cols:
        conn.execute(
            "ALTER TABLE spec_rule ADD COLUMN recommended_regions_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "region_reasoning" not in cols:
        conn.execute(
            "ALTER TABLE spec_rule ADD COLUMN region_reasoning TEXT NOT NULL DEFAULT ''"
        )
    cols = _table_cols(conn, "spec_rule")
    if "source_trace_json" not in cols:
        conn.execute(
            "ALTER TABLE spec_rule ADD COLUMN source_trace_json TEXT NOT NULL DEFAULT '{}'"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spec_rule_doc ON spec_rule(doc_id)")


def _drop_legacy_equipment_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "spec_rule_equipment"):
        conn.execute("DROP TABLE spec_rule_equipment")


def db_path() -> Path:
    return spec_db_path()


def _json_list_field(r: sqlite3.Row, key: str) -> list[str]:
    keys = r.keys()
    if key not in keys:
        return []
    try:
        raw = json.loads(str(r[key] or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    keys = r.keys()
    recommended_algorithms = _json_list_field(r, "recommended_algorithms_json")
    recommended_regions = _json_list_field(r, "recommended_regions_json")
    recommended_equipment = _json_list_field(r, "recommended_equipment_json")

    algorithm_reasoning = str(
        r["algorithm_reasoning"] if "algorithm_reasoning" in keys else ""
    )
    region_reasoning = str(r["region_reasoning"] if "region_reasoning" in keys else "")

    try:
        recommended_regions = json.loads(
            str(
                r["recommended_regions_json"]
                if "recommended_regions_json" in keys
                else "[]"
            )
        )
    except json.JSONDecodeError:
        recommended_regions = []
    if not isinstance(recommended_regions, list):
        recommended_regions = []

    region_reasoning = str(r["region_reasoning"] if "region_reasoning" in keys else "")

    try:
        source_trace = json.loads(
            str(r["source_trace_json"] if "source_trace_json" in keys else "{}")
        )
    except json.JSONDecodeError:
        source_trace = {}
    if not isinstance(source_trace, dict):
        source_trace = {}

    return {
        "rule_id": r["rule_id"],
        "name": r["name"],
        "desc": r["desc"],
        "source": r["source"],
        "level": r["level"],
        "requirements": r["requirements"],
        "doc_id": r["doc_id"],
        "status": r["status"],
        "recommended_algorithms": recommended_algorithms,
        "algorithm_reasoning": algorithm_reasoning,
        "recommended_regions": recommended_regions,
        "region_reasoning": region_reasoning,
        "recommended_equipment": recommended_equipment,
        "source_trace": source_trace,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }

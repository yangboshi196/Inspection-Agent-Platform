"""算法实体 SQLite 表结构。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import algorithm_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS algorithm (
    algorithm_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    schema_json TEXT NOT NULL DEFAULT '{}',
    health TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_algorithm_health ON algorithm(health);
CREATE INDEX IF NOT EXISTS idx_algorithm_name ON algorithm(name);
"""


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def db_path() -> Path:
    return algorithm_db_path()


def row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    import json

    raw = str(r["schema_json"] or "{}").strip() or "{}"
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError:
        schema = {}
    return {
        "algorithm_id": str(r["algorithm_id"]),
        "name": str(r["name"]),
        "desc": str(r["desc"] or ""),
        "link": str(r["link"] or ""),
        "schema": schema,
        "health": str(r["health"] or "unknown"),
    }

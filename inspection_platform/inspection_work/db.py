"""巡检业务（work）表结构。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import inspection_work_db_path
from inspection_platform.app.mysql_compat import row_get, row_keys

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspection_work (
    work_id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL,
    region_ids_json TEXT NOT NULL DEFAULT '[]',
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    rule_set_json TEXT NOT NULL DEFAULT '[]',
    algorithm_set_json TEXT NOT NULL DEFAULT '[]',
    equipment_set_json TEXT NOT NULL DEFAULT '[]',
    work_status TEXT NOT NULL DEFAULT 'online',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspection_work_region ON inspection_work(region_id);
CREATE INDEX IF NOT EXISTS idx_inspection_work_created ON inspection_work(created_at DESC);
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
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _rename_legacy_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "review_work") and not _table_exists(conn, "inspection_work"):
        conn.execute("ALTER TABLE review_work RENAME TO inspection_work")


def _migrate_inspection_work(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "inspection_work"):
        return
    cols = _table_cols(conn, "inspection_work")
    if "algorithm_set_json" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN algorithm_set_json TEXT NOT NULL DEFAULT '[]'"
        )
    cols = _table_cols(conn, "inspection_work")
    if "schedule_mode" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN schedule_mode TEXT NOT NULL DEFAULT 'manual'"
        )
    if "schedule_interval" not in cols:
        conn.execute("ALTER TABLE inspection_work ADD COLUMN schedule_interval TEXT")
    if "schedule_times" not in cols:
        conn.execute("ALTER TABLE inspection_work ADD COLUMN schedule_times TEXT")
    if "source" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
        )
    if "equipment_algo_params_json" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN equipment_algo_params_json TEXT NOT NULL DEFAULT '{}'"
        )
    cols = _table_cols(conn, "inspection_work")
    if "region_ids_json" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN region_ids_json TEXT NOT NULL DEFAULT '[]'"
        )
    cols = _table_cols(conn, "inspection_work")
    if "work_status" not in cols:
        conn.execute(
            "ALTER TABLE inspection_work ADD COLUMN work_status TEXT NOT NULL DEFAULT 'online'"
        )


def db_path() -> Path:
    return inspection_work_db_path()


def row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    import json

    keys = row_keys(r)
    try:
        rule_set = json.loads(str(r["rule_set_json"] or "[]"))
    except json.JSONDecodeError:
        rule_set = []
    try:
        equipment_set = json.loads(str(r["equipment_set_json"] or "[]"))
    except json.JSONDecodeError:
        equipment_set = []
    try:
        algorithm_set = json.loads(str(r["algorithm_set_json"] or "[]"))
    except json.JSONDecodeError:
        algorithm_set = []
    if not isinstance(rule_set, list):
        rule_set = []
    if not isinstance(equipment_set, list):
        equipment_set = []
    if not isinstance(algorithm_set, list):
        algorithm_set = []
    try:
        equipment_algo_params = json.loads(
            str(row_get(r, "equipment_algo_params_json", "{}"))
        )
    except json.JSONDecodeError:
        equipment_algo_params = {}
    if not isinstance(equipment_algo_params, dict):
        equipment_algo_params = {}
    try:
        region_ids = json.loads(str(row_get(r, "region_ids_json", "[]")))
    except json.JSONDecodeError:
        region_ids = []
    if not isinstance(region_ids, list):
        region_ids = []
    region_ids = [str(x).strip() for x in region_ids if str(x).strip()]
    if not region_ids and r["region_id"]:
        region_ids = [str(r["region_id"])]

    return {
        "work_id": str(r["work_id"]),
        "name": str(r["name"]),
        "region_id": str(r["region_id"]),
        "region_ids": region_ids,
        "work_status": str(row_get(r, "work_status", "online")),
        "desc": str(r["desc"] or ""),
        "rule_set": rule_set,
        "algorithm_set": algorithm_set,
        "equipment_set": equipment_set,
        "equipment_algo_params": equipment_algo_params,
        "schedule_mode": str(row_get(r, "schedule_mode", "manual") or "manual"),
        "schedule_interval": row_get(r, "schedule_interval"),
        "schedule_times": row_get(r, "schedule_times"),
        "source": str(row_get(r, "source", "manual") or "manual"),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }

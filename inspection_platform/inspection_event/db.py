"""巡检事件表结构。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import inspection_event_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspection_event (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    work_id TEXT NOT NULL DEFAULT '',
    work_name TEXT NOT NULL DEFAULT '',
    region_id TEXT NOT NULL DEFAULT '',
    region_name TEXT NOT NULL DEFAULT '',
    equipment_id TEXT NOT NULL DEFAULT '',
    algorithm_name TEXT NOT NULL DEFAULT '',
    rule_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    value_num REAL,
    threshold_text TEXT NOT NULL DEFAULT '',
    snapshot_gradient TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    reported_at TEXT NOT NULL DEFAULT '',
    handler TEXT NOT NULL DEFAULT '',
    handled_at TEXT NOT NULL DEFAULT '',
    resolution_outcome TEXT NOT NULL DEFAULT '',
    resolution_detail TEXT NOT NULL DEFAULT '',
    detection_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ie_kind ON inspection_event(kind);
CREATE INDEX IF NOT EXISTS idx_ie_status ON inspection_event(status);
CREATE INDEX IF NOT EXISTS idx_ie_work ON inspection_event(work_id);
CREATE INDEX IF NOT EXISTS idx_ie_region ON inspection_event(region_id);
CREATE INDEX IF NOT EXISTS idx_ie_occurred ON inspection_event(occurred_at DESC);
"""


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def db_path() -> Path:
    return inspection_event_db_path()


def row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    keys = set(r.keys()) if hasattr(r, "keys") else set()
    return {
        "event_id": str(r["event_id"]),
        "kind": str(r["kind"]),
        "title": str(r["title"]),
        "source_name": str(r["source_name"] or ""),
        "work_id": str(r["work_id"] or ""),
        "work_name": str(r["work_name"] or ""),
        "region_id": str(r["region_id"] or ""),
        "region_name": str(r["region_name"] or ""),
        "equipment_id": str(r["equipment_id"] or ""),
        "algorithm_name": str(r["algorithm_name"] or ""),
        "rule_name": str(r["rule_name"] or ""),
        "status": str(r["status"] or "pending"),
        "value_num": r["value_num"],
        "threshold_text": str(r["threshold_text"] or ""),
        "snapshot_gradient": str(r["snapshot_gradient"] or ""),
        "occurred_at": str(r["occurred_at"]),
        "reported_at": str(r["reported_at"] or ""),
        "handler": str(r["handler"] or ""),
        "handled_at": str(r["handled_at"] or ""),
        "resolution_outcome": str(r["resolution_outcome"] or ""),
        "resolution_detail": str(r["resolution_detail"] or ""),
        "detection_json": str(r["detection_json"] or "") if "detection_json" in keys else "",
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }

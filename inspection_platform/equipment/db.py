"""设备 SQLite 表结构。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import equipment_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    region_id TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    platform_name TEXT NOT NULL DEFAULT '',
    platform_address TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    online INTEGER NOT NULL DEFAULT 1,
    simulate_video_relpath TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_equipment_kind ON equipment(kind);
CREATE INDEX IF NOT EXISTS idx_equipment_region ON equipment(region_id);

CREATE TABLE IF NOT EXISTS sensor_reading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    value REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sensor_reading_equipment ON sensor_reading(equipment_id, recorded_at DESC);
"""


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def db_path() -> Path:
    return equipment_db_path()


def row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    eid = str(r["id"])
    rel = ""
    try:
        rel = str(r["simulate_video_relpath"] or "")
    except (KeyError, IndexError):
        rel = ""
    return {
        "id": eid,
        "kind": str(r["kind"]),
        "name": str(r["name"]),
        "region_id": str(r["region_id"] or ""),
        "description": str(r["description"] or ""),
        "platform_name": str(r["platform_name"] or ""),
        "platform_address": str(r["platform_address"] or ""),
        "thumbnail": str(r["thumbnail"] or ""),
        "data_type": str(r["data_type"] or ""),
        "unit": str(r["unit"] or ""),
        "online": bool(int(r["online"] or 0)),
        "simulate_video_relpath": rel,
        "simulate_video_url": _simulate_video_url(eid, rel, str(r["updated_at"])),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }


def _simulate_video_url(equipment_id: str, relpath: str, updated_at: str) -> str:
    if not relpath.strip():
        return ""
    q = quote(updated_at.strip(), safe="")
    # 走 /data 静态托管，避免 <video> 无法带 Bearer 导致 /api 401
    rel = relpath.strip().lstrip("/")
    return f"/data/{rel}?v={q}"


def reading_row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "time": str(r["recorded_at"]),
        "value": float(r["value"]),
        "status": str(r["status"] or "normal"),
    }

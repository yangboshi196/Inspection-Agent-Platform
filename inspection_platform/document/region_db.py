"""region 元数据表（MySQL region 表）；路径 env 仅兼容旧 SQLite 部署说明。

环境变量::

    SIA_REGION_SQLITE_PATH  (REGION_DB_PATH) — 历史文档，当前读写走 MySQL
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from inspection_platform.envutil import env_first

REGION_TABLE = "region"

REGION_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {REGION_TABLE} (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    "desc" TEXT NOT NULL DEFAULT '',
    parent_id TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

_region_bootstrapped = False
_bootstrap_lock = threading.Lock()


def _migrate_region(conn: sqlite3.Connection) -> None:
    cur = conn.execute(f"PRAGMA table_info({REGION_TABLE})")
    cols = {str(row[1]) for row in cur.fetchall()}
    if "parent_id" not in cols:
        conn.execute(
            f'ALTER TABLE {REGION_TABLE} ADD COLUMN parent_id TEXT NOT NULL DEFAULT \'\'',
        )
    if "sort_order" not in cols:
        conn.execute(
            f"ALTER TABLE {REGION_TABLE} ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
        )
    cur = conn.execute(f"SELECT 1 FROM {REGION_TABLE} WHERE id = 'r0'")
    if cur.fetchone() is None:
        conn.execute(
            f"""
            INSERT INTO {REGION_TABLE} (id, name, "desc", parent_id, sort_order, created_at)
            VALUES ('r0', '星河智慧物业 · 示范园区', '物业服务根区域，下辖写字楼、商业、地库及外围子区域。', '', 0, datetime('now'))
            """,
        )


def _region_db_path_env() -> str:
    return env_first("SIA_REGION_SQLITE_PATH", "REGION_DB_PATH")


def region_db_path() -> Path:
    env = _region_db_path_env()
    if env:
        return Path(env).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    flat = (repo_root / "data" / "region.db").resolve()
    nested = (repo_root / "data" / "region" / "region.db").resolve()
    if flat.exists():
        return flat
    if nested.exists():
        return nested
    return flat


def init_region_db() -> None:
    """应用 lifespan 调用一次：若缺根区域 r0 则插入（勿在请求路径调用）。"""
    global _region_bootstrapped
    if _region_bootstrapped:
        return
    with _bootstrap_lock:
        if _region_bootstrapped:
            return
        from datetime import datetime, timezone

        from inspection_platform.app.database import get_connection

        conn = get_connection()
        try:
            row = conn.execute("SELECT 1 FROM region WHERE id = ?", ("r0",)).fetchone()
            if row is None:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn.execute(
                    """
                    INSERT INTO region (id, name, `desc`, parent_id, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "r0",
                        "星河智慧物业 · 示范园区",
                        "物业服务根区域，下辖写字楼、商业、地库及外围子区域。",
                        "",
                        0,
                        now,
                    ),
                )
                conn.commit()
        finally:
            conn.close()
        _region_bootstrapped = True


def get_region_connection():
    """请求路径直接取连接；表结构/种子仅在 lifespan 初始化。"""
    from inspection_platform.app.database import get_connection

    return get_connection()

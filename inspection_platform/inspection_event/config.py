"""巡检事件 SQLite 路径。"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def inspection_event_db_path() -> Path:
    env = env_first("SIA_INSPECTION_EVENT_SQLITE_PATH", "INSPECTION_EVENT_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "inspection_event.db").resolve()

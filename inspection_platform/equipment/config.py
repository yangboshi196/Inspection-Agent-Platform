"""设备模块 SQLite 路径。"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def equipment_db_path() -> Path:
    env = env_first("SIA_EQUIPMENT_SQLITE_PATH", "EQUIPMENT_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "equipment.db").resolve()

"""认证 SQLite 路径。"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def auth_db_path() -> Path:
    env = env_first("SIA_AUTH_SQLITE_PATH", "AUTH_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "auth.db").resolve()

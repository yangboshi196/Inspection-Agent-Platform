"""算法模块 SQLite 路径。

环境变量::

    SIA_ALGORITHM_SQLITE_PATH  (ALGORITHM_DB_PATH)
"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def algorithm_db_path() -> Path:
    env = env_first("SIA_ALGORITHM_SQLITE_PATH", "ALGORITHM_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "algorithm.db").resolve()

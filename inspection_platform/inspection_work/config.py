"""巡检业务 SQLite 路径。

环境变量::

    SIA_INSPECTION_WORK_SQLITE_PATH  (INSPECTION_WORK_DB_PATH)
    兼容旧名 SIA_REVIEW_WORK_SQLITE_PATH / REVIEW_WORK_DB_PATH
"""

from __future__ import annotations

import shutil
from pathlib import Path

from inspection_platform.envutil import env_first


def inspection_work_db_path() -> Path:
    env = env_first(
        "SIA_INSPECTION_WORK_SQLITE_PATH",
        "INSPECTION_WORK_DB_PATH",
        "SIA_REVIEW_WORK_SQLITE_PATH",
        "REVIEW_WORK_DB_PATH",
    )
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    new_path = (root / "data" / "inspection_work.db").resolve()
    old_path = (root / "data" / "review_work.db").resolve()
    if not new_path.exists() and old_path.exists():
        shutil.move(str(old_path), str(new_path))
    return new_path

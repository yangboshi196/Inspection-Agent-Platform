"""报告库 SQLite 路径。"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def report_db_path() -> Path:
    env = env_first("SIA_REPORT_SQLITE_PATH", "REPORT_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "report.db").resolve()

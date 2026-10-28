"""业务追踪：从巡检事件探测真实执行时间（与追踪服务解耦）。"""

from __future__ import annotations

from inspection_platform.app.database import get_connection


def earliest_execution_at(work_id: str) -> str | None:
    """取该业务在 inspection_event 中最早的发生时间，用于发布时回填 started_at。"""
    wid = work_id.strip()
    if not wid:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """
SELECT MIN(occurred_at) AS t FROM inspection_event
WHERE work_id = ?
""",
            (wid,),
        ).fetchone()
    finally:
        conn.close()
    if not row or row["t"] is None:
        return None
    return str(row["t"])

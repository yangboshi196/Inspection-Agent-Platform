"""巡检业务追踪队列：发布/下架、状态与列表查询。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from inspection_platform.app.database import get_connection

from .service import InspectionWorkService
from .tracking_probe import earliest_execution_at
from .tracking_times import (
    estimate_running_end,
    estimate_waiting_window,
    parse_db_datetime,
    resolve_publish_snapshot,
    validate_schedule_fields,
)


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WorkTrackingService:
    def ensure_ready(self) -> None:
        from inspection_platform.app.database import init_db

        init_db()

    def _apply_live_schedule_fields(
        self, api: dict[str, Any], work: dict[str, Any]
    ) -> dict[str, Any]:
        """按当前 work 配置实时推算列表展示用的时间字段。"""
        status = str(api.get("queue_status") or "")
        mode = str(work.get("schedule_mode") or "manual")

        if status == "waiting":
            est_start, est_end = estimate_waiting_window(work)
            api["estimated_start_at"] = est_start
            api["estimated_end_at"] = est_end
            return api

        if status == "running":
            if mode == "continuous":
                api["estimated_end_at"] = None
            else:
                started = parse_db_datetime(api.get("started_at"))
                if started:
                    api["estimated_end_at"] = estimate_running_end(work, started_at=started)
        return api

    def _row_to_api(self, row: Any, work: dict[str, Any] | None = None) -> dict[str, Any]:
        if row is None:
            return {}
        wid = str(row["work_id"])
        if work is None:
            work = InspectionWorkService().get(wid) or {}
        api = {
            "work_id": wid,
            "work_name": str(work.get("name") or wid),
            "schedule_mode": str(work.get("schedule_mode") or "manual"),
            "published": bool(int(row["published"] or 0)),
            "queue_status": str(row["queue_status"] or "waiting"),
            "published_at": str(row["published_at"]) if row["published_at"] else None,
            "started_at": str(row["started_at"]) if row["started_at"] else None,
            "ended_at": str(row["ended_at"]) if row["ended_at"] else None,
            "estimated_start_at": str(row["estimated_start_at"]) if row["estimated_start_at"] else None,
            "estimated_end_at": str(row["estimated_end_at"]) if row["estimated_end_at"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        return self._apply_live_schedule_fields(api, work)

    def get(self, work_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        wid = work_id.strip()
        if not wid:
            return None
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM inspection_work_tracking WHERE work_id = ?",
                (wid,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        work = InspectionWorkService().get(wid)
        return self._row_to_api(row, work)

    def is_published(self, work_id: str) -> bool:
        row = self.get(work_id)
        return bool(row and row.get("published"))

    def list_published(
        self,
        *,
        queue_status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_ready()
        conn = get_connection()
        try:
            if queue_status:
                rows = conn.execute(
                    """
SELECT * FROM inspection_work_tracking
WHERE published = 1 AND queue_status = ?
ORDER BY updated_at DESC
""",
                    (queue_status.strip(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
SELECT * FROM inspection_work_tracking
WHERE published = 1
ORDER BY updated_at DESC
"""
                ).fetchall()
        finally:
            conn.close()
        work_svc = InspectionWorkService()
        work_svc.ensure_ready()
        out: list[dict[str, Any]] = []
        for row in rows:
            wid = str(row["work_id"])
            work = work_svc.get(wid)
            if not work:
                continue
            out.append(self._row_to_api(row, work))
        return out

    def summary(self) -> dict[str, int]:
        self.ensure_ready()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
SELECT queue_status, COUNT(*) AS c FROM inspection_work_tracking
WHERE published = 1
GROUP BY queue_status
"""
            ).fetchall()
        finally:
            conn.close()
        counts = {"waiting": 0, "running": 0, "completed": 0}
        for row in rows:
            key = str(row["queue_status"] or "")
            if key in counts:
                counts[key] = int(row["c"] or 0)
        counts["total"] = counts["waiting"] + counts["running"] + counts["completed"]
        return counts

    def publish(self, work_id: str) -> dict[str, Any]:
        self.ensure_ready()
        wid = work_id.strip()
        work_svc = InspectionWorkService()
        work_svc.ensure_ready()
        work = work_svc.get(wid)
        if not work:
            raise ValueError("巡检业务不存在，请先保存业务")
        validate_schedule_fields(
            str(work.get("schedule_mode") or "manual"),
            work.get("schedule_interval"),
            work.get("schedule_times"),
        )
        now = _display_now()
        snapshot = resolve_publish_snapshot(
            work,
            earliest_execution_at=earliest_execution_at(wid),
        )

        conn = get_connection()
        try:
            conn.execute(
                """
INSERT INTO inspection_work_tracking (
    work_id, published, queue_status, published_at, started_at, ended_at,
    estimated_start_at, estimated_end_at, created_at, updated_at
) VALUES (?, 1, ?, ?, ?, NULL, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
    published = 1,
    queue_status = VALUES(queue_status),
    published_at = VALUES(published_at),
    started_at = VALUES(started_at),
    ended_at = NULL,
    estimated_start_at = VALUES(estimated_start_at),
    estimated_end_at = VALUES(estimated_end_at),
    updated_at = VALUES(updated_at)
""",
                (
                    wid,
                    snapshot["queue_status"],
                    now,
                    snapshot["started_at"],
                    snapshot["estimated_start_at"],
                    snapshot["estimated_end_at"],
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        row = self.get(wid)
        if not row:
            raise ValueError("发布失败")
        return row

    def unpublish(self, work_id: str) -> dict[str, Any]:
        self.ensure_ready()
        wid = work_id.strip()
        now = _display_now()
        conn = get_connection()
        try:
            cur = conn.execute(
                """
UPDATE inspection_work_tracking
SET published = 0, updated_at = ?
WHERE work_id = ?
""",
                (now, wid),
            )
            conn.commit()
            if cur.rowcount <= 0:
                raise ValueError("该业务尚未发布到业务追踪")
        finally:
            conn.close()
        return self.get(wid) or {"work_id": wid, "published": False}

    def sync_schedule_config(self, work_id: str) -> None:
        """运行周期保存后，同步已发布业务的追踪队列（含 completed/running 重入队）。"""
        self.ensure_ready()
        wid = work_id.strip()
        conn = get_connection()
        try:
            row = conn.execute(
                """
SELECT queue_status, started_at FROM inspection_work_tracking
WHERE work_id = ? AND published = 1
""",
                (wid,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return

        work = InspectionWorkService().get(wid) or {}
        mode = str(work.get("schedule_mode") or "manual")
        status = str(row["queue_status"] or "waiting")
        now = _display_now()
        est_start, est_end = estimate_waiting_window(work)

        conn = get_connection()
        try:
            if mode == "manual":
                if status != "waiting":
                    return
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET estimated_start_at = NULL, estimated_end_at = NULL, updated_at = ?
WHERE work_id = ? AND published = 1 AND queue_status = 'waiting'
""",
                    (now, wid),
                )
            elif status == "waiting":
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET estimated_start_at = ?, estimated_end_at = ?, updated_at = ?
WHERE work_id = ? AND published = 1 AND queue_status = 'waiting'
""",
                    (est_start, est_end, now, wid),
                )
            elif status == "running" and mode == "continuous" and row["started_at"]:
                # 持续监控已在跑：保留 started_at，仅清空预计结束
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET estimated_end_at = NULL, updated_at = ?
WHERE work_id = ? AND published = 1 AND queue_status = 'running'
""",
                    (now, wid),
                )
            else:
                # completed 或调度模式切换：按新周期重新进入等待队列
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET queue_status = 'waiting',
    started_at = NULL,
    ended_at = NULL,
    estimated_start_at = ?,
    estimated_end_at = ?,
    updated_at = ?
WHERE work_id = ? AND published = 1
""",
                    (est_start, est_end, now, wid),
                )
            conn.commit()
        finally:
            conn.close()

    def _resolve_running_start(self, row: dict[str, Any], work: dict[str, Any]) -> str:
        """确定本次 running 的开始时间。

        - manual：每次触发取当前时刻（不保留历史发布/持续监控残留）
        - periodic/scheduled：优先计划时刻
        - 其余：保留进行中已有 started_at
        """
        mode = str(work.get("schedule_mode") or "manual")
        if mode == "manual":
            return _display_now()
        if row.get("started_at") and row.get("queue_status") == "running":
            return str(row["started_at"])
        if mode in ("periodic", "scheduled") and row.get("estimated_start_at"):
            return str(row["estimated_start_at"])
        return _display_now()

    def mark_running(self, work_id: str) -> None:
        row = self.get(work_id)
        if not row or not row.get("published"):
            return
        work = InspectionWorkService().get(work_id.strip()) or {}
        # get() 对 waiting 会 overlay 预计时间，此处用实时配置
        if row.get("queue_status") == "waiting":
            est_start, est_end = estimate_waiting_window(work)
            row = {**row, "estimated_start_at": est_start, "estimated_end_at": est_end}
        started_at = self._resolve_running_start(row, work)
        started_dt = parse_db_datetime(started_at) or datetime.now()
        est_end = estimate_running_end(work, started_at=started_dt)
        now = _display_now()
        conn = get_connection()
        try:
            conn.execute(
                """
UPDATE inspection_work_tracking
SET queue_status = 'running',
    started_at = ?,
    ended_at = NULL,
    estimated_end_at = ?,
    updated_at = ?
WHERE work_id = ? AND published = 1
""",
                (started_at, est_end, now, work_id.strip()),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_completed(self, work_id: str) -> None:
        row = self.get(work_id)
        if not row or not row.get("published"):
            return
        work = InspectionWorkService().get(work_id.strip()) or {}
        mode = str(work.get("schedule_mode") or "")
        if mode == "continuous":
            return
        now = _display_now()
        conn = get_connection()
        try:
            if mode in ("periodic", "scheduled"):
                est_start, est_end = estimate_waiting_window(work)
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET queue_status = 'completed',
    ended_at = ?,
    estimated_start_at = ?,
    estimated_end_at = ?,
    updated_at = ?
WHERE work_id = ? AND published = 1
""",
                    (now, est_start, est_end, now, work_id.strip()),
                )
            else:
                conn.execute(
                    """
UPDATE inspection_work_tracking
SET queue_status = 'completed',
    ended_at = ?,
    updated_at = ?
WHERE work_id = ? AND published = 1
""",
                    (now, now, work_id.strip()),
                )
            conn.commit()
        finally:
            conn.close()

    def ensure_running_for_continuous(self, work_id: str) -> None:
        """持续监控首次 tick：waiting → running，started_at 取真实 tick 时刻。"""
        row = self.get(work_id)
        if not row or not row.get("published"):
            return
        if row.get("queue_status") != "waiting":
            return
        self.mark_running(work_id)

    def tick_scheduled_modes(self) -> list[str]:
        """周期/定时检查：到达预计窗口时推进 waiting↔running↔completed。

        返回本 tick 新进入 running、需要执行算法的工作 ID 列表。
        """
        now = datetime.now()
        work_svc = InspectionWorkService()
        work_svc.ensure_ready()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
SELECT work_id, queue_status, estimated_start_at, estimated_end_at
FROM inspection_work_tracking WHERE published = 1
"""
            ).fetchall()
        finally:
            conn.close()
        to_run: list[str] = []
        for row in rows:
            wid = str(row["work_id"])
            work = work_svc.get(wid)
            if not work:
                continue
            mode = str(work.get("schedule_mode") or "")
            if mode not in ("periodic", "scheduled"):
                continue
            if str(work.get("work_status") or "online") == "offline":
                continue
            status = str(row["queue_status"] or "")
            est_start, est_end = estimate_waiting_window(work)
            if status in ("waiting", "completed"):
                win_start = parse_db_datetime(
                    str(row["estimated_start_at"]) if row["estimated_start_at"] else est_start
                )
                if not win_start:
                    win_start = parse_db_datetime(est_start)
                if win_start and now >= win_start:
                    self.mark_running(wid)
                    to_run.append(wid)
            elif status == "running":
                win_end = parse_db_datetime(
                    str(row["estimated_end_at"]) if row["estimated_end_at"] else est_end
                )
                if win_end and now >= win_end:
                    self.mark_completed(wid)
        return to_run

    def require_published_for_manual(self, work_id: str) -> None:
        if not self.is_published(work_id):
            raise ValueError("请先发布业务后再触发")

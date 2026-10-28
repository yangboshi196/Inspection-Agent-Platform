"""周期/定时检查：按预计窗口推进业务追踪队列，并触发算法执行。"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


class WorkTrackingScheduleTicker:
    def __init__(self, interval_sec: int = 30) -> None:
        self._interval = max(10, int(interval_sec))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._work_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._last_exec_started: dict[str, str] = {}

    def start(self) -> None:
        if os.environ.get("SIA_TRACKING_SCHEDULER", "1").strip().lower() in (
            "0",
            "false",
            "no",
        ):
            logger.info("work tracking schedule ticker disabled by env")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="work-tracking-schedule-ticker", daemon=True
        )
        self._thread.start()
        logger.info("work tracking schedule ticker started (interval=%ss)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                logger.exception("work tracking schedule tick failed")

    def tick(self) -> None:
        from inspection_platform.inspection_work.runner import InspectionWorkRunner
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        tracking = WorkTrackingService()
        started_ids = tracking.tick_scheduled_modes()
        if not started_ids:
            return

        runner = InspectionWorkRunner()
        for wid in started_ids:
            row = tracking.get(wid) or {}
            started_at = str(row.get("started_at") or "")
            with self._locks_guard:
                if self._last_exec_started.get(wid) == started_at:
                    logger.debug(
                        "周期/定时跳过重复执行 work_id=%s started_at=%s",
                        wid,
                        started_at,
                    )
                    continue
                lock = self._work_locks.setdefault(wid, threading.Lock())
            if not lock.acquire(blocking=False):
                logger.info("周期/定时跳过 work_id=%s（上一轮仍在执行）", wid)
                continue

            def _run(wid: str = wid, started_at: str = started_at) -> None:
                try:
                    result = runner.run_scheduled_tick(wid)
                    if result.get("skipped"):
                        return
                    with self._locks_guard:
                        self._last_exec_started[wid] = started_at
                    logger.info(
                        "周期/定时窗口执行完成 work_id=%s events=%s warnings=%s",
                        wid,
                        result.get("events_created"),
                        len(result.get("warnings") or []),
                    )
                except Exception:
                    logger.exception("周期/定时窗口执行失败 work_id=%s", wid)
                finally:
                    lock.release()

            threading.Thread(
                target=_run,
                name=f"scheduled-work-{wid[:12]}",
                daemon=True,
            ).start()


work_tracking_schedule_ticker = WorkTrackingScheduleTicker()

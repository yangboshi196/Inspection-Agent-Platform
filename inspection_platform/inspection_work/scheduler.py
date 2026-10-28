"""持续监控后台调度：每 10 秒对在线 continuous 业务执行一次分析 tick。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from inspection_platform.inspection_work.runner import (
    CONTINUOUS_CHECK_INTERVAL_SEC,
    InspectionWorkRunner,
)
from inspection_platform.inspection_work.service import InspectionWorkService

logger = logging.getLogger(__name__)


class ContinuousWorkScheduler:
    def __init__(self, interval_sec: int = CONTINUOUS_CHECK_INTERVAL_SEC) -> None:
        self._interval = max(5, int(interval_sec))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._work_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def start(self) -> None:
        if os.environ.get("SIA_CONTINUOUS_SCHEDULER", "1").strip().lower() in (
            "0",
            "false",
            "no",
        ):
            logger.info("continuous work scheduler disabled by env")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="continuous-work-scheduler", daemon=True
        )
        self._thread.start()
        logger.info(
            "continuous work scheduler started (interval=%ss, window=%ss)",
            self._interval,
            CONTINUOUS_CHECK_INTERVAL_SEC,
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                logger.exception("continuous work scheduler tick failed")

    def tick(self) -> None:
        svc = InspectionWorkService()
        items: list[dict[str, Any]] = []
        offset = 0
        limit = 500
        while True:
            batch, total = svc.list_all(limit=limit, offset=offset)
            items.extend(batch)
            offset += limit
            if offset >= total:
                break
        runner = InspectionWorkRunner()
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        tracking = WorkTrackingService()
        for work in items:
            if str(work.get("schedule_mode") or "") != "continuous":
                continue
            if str(work.get("work_status") or "online") == "offline":
                continue
            wid = str(work.get("work_id") or "").strip()
            if not wid:
                continue
            if not tracking.is_published(wid):
                continue
            with self._locks_guard:
                lock = self._work_locks.setdefault(wid, threading.Lock())
            if not lock.acquire(blocking=False):
                logger.info("持续监控跳过 work_id=%s（上一轮仍在执行）", wid)
                continue
            try:
                result = runner.run_continuous_tick(wid)
                if result.get("skipped"):
                    continue
                logger.info(
                    "持续监控 tick 完成 work_id=%s events=%s warnings=%s",
                    wid,
                    result.get("events_created"),
                    len(result.get("warnings") or []),
                )
            except Exception:
                logger.exception("持续监控 tick 失败 work_id=%s", wid)
            finally:
                lock.release()


continuous_work_scheduler = ContinuousWorkScheduler()

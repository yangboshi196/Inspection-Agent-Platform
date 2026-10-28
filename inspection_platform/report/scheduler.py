"""报告计划后台调度：按 generate_time 触发自动生成。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from .service import ReportService

logger = logging.getLogger(__name__)


def _normalize_hm(raw: str) -> str:
    s = (raw or "08:00").strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return "08:00"


def _plan_due_today(plan: dict, now: datetime) -> bool:
    freq = str(plan.get("frequency") or "daily")
    if freq == "daily":
        return True
    if freq == "weekly":
        weekday = plan.get("weekday")
        target = int(weekday) if weekday is not None else 1
        return now.isoweekday() == target
    if freq == "monthly":
        month_day = plan.get("month_day")
        target = int(month_day) if month_day is not None else 1
        return now.day == target
    return False


class ReportScheduler:
    """每分钟检查启用的报告计划，在匹配时刻触发一次生成。"""

    def __init__(self, interval_sec: int = 60) -> None:
        self._interval = max(10, int(interval_sec))
        self._last_run: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="report-scheduler", daemon=True)
        self._thread.start()
        logger.info("report scheduler started (interval=%ss)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                logger.exception("report scheduler tick failed")

    def tick(self) -> None:
        now = datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        current_hm = now.strftime("%H:%M")

        svc = ReportService()
        plans, _ = svc.list_plans(enabled=True, limit=500)

        for plan in plans:
            if not plan.get("enabled"):
                continue
            if _normalize_hm(str(plan.get("generate_time") or "")) != current_hm:
                continue
            if not _plan_due_today(plan, now):
                continue

            pid = str(plan.get("plan_id") or "")
            if not pid:
                continue
            if self._last_run.get(pid) == minute_key:
                continue

            try:
                svc.generate_from_plan(pid, source="scheduled")
                self._last_run[pid] = minute_key
                logger.info("scheduled report generated for plan %s", pid)
            except ValueError:
                logger.warning("skip scheduled report for plan %s: plan not found", pid)
            except Exception:
                logger.exception("failed scheduled report for plan %s", pid)


report_scheduler = ReportScheduler()

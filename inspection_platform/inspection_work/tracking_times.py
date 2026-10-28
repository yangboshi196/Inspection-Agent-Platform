"""业务追踪：按运行周期推算时间窗口（存储层，不含 UI 文案）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any


def _now() -> datetime:
    return datetime.now()


def fmt_db(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_db_datetime(raw: str | None) -> datetime | None:
    """解析追踪/事件时间字符串，统一为 naive 本地时间便于比较。"""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    # ISO 8601：2026-06-26T11:52:08Z
    if "T" in text:
        iso = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except ValueError:
            text = text.replace("T", " ")
    else:
        text = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def normalize_stored_at(raw: str | None) -> str | None:
    """将事件时间等异构格式规范为 DB 存储用的 YYYY-MM-DD HH:MM:SS。"""
    if not raw or not str(raw).strip():
        return None
    dt = parse_db_datetime(raw)
    return fmt_db(dt) if dt else str(raw).strip()


def _normalize_schedule_times(raw: str) -> str:
    """兼容 UI 输入「16 : 00」「16：00」等带空格或全角冒号的触发时刻。"""
    text = str(raw or "").replace("：", ":")
    parts: list[str] = []
    for chunk in re.split(r"[,，]", text):
        compact = re.sub(r"\s+", "", chunk.strip())
        if compact:
            parts.append(compact)
    return ",".join(parts)


def _parse_times_csv(raw: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in _normalize_schedule_times(raw).split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})$", part)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def _next_scheduled_slot(now: datetime, times_csv: str) -> datetime:
    slots = _parse_times_csv(times_csv)
    if not slots:
        return now + timedelta(hours=1)
    candidates: list[datetime] = []
    for day_offset in (0, 1):
        base = now.replace(second=0, microsecond=0) + timedelta(days=day_offset)
        for hour, minute in slots:
            cand = base.replace(hour=hour % 24, minute=minute)
            if day_offset == 0 and cand <= now:
                continue
            candidates.append(cand)
    if not candidates:
        h, m = slots[0]
        tomorrow = (now + timedelta(days=1)).replace(
            hour=h % 24, minute=m, second=0, microsecond=0
        )
        return tomorrow
    return min(candidates)


def _periodic_duration(interval: str) -> timedelta:
    text = (interval or "").strip()
    if not text:
        return timedelta(days=1)
    if "小时" in text:
        m = re.search(r"(\d+)", text)
        hours = int(m.group(1)) if m else 1
        return timedelta(hours=max(1, hours))
    if "周" in text:
        return timedelta(days=7)
    if "月" in text:
        return timedelta(days=30)
    return timedelta(days=1)


def _next_periodic_start(now: datetime, interval: str) -> datetime:
    if "小时" in (interval or ""):
        return now + timedelta(minutes=5)
    return now + timedelta(minutes=10)


def estimate_waiting_window(
    work: dict[str, Any], *, base: datetime | None = None
) -> tuple[str | None, str | None]:
    """等待中写入 DB 的预计开始/结束。

    - manual：无预计时间（由前端展示「等待手动触发」）
    - continuous：仅有预计开始，无预计结束
    - periodic / scheduled：按配置推算下一窗口
    """
    now = base or _now()
    mode = str(work.get("schedule_mode") or "manual").strip()
    if mode == "manual":
        return None, None
    if mode == "scheduled":
        start = _next_scheduled_slot(now, str(work.get("schedule_times") or "08:00"))
        return fmt_db(start), fmt_db(start + timedelta(hours=1))
    if mode == "periodic":
        start = _next_periodic_start(now, str(work.get("schedule_interval") or "每日"))
        end = start + _periodic_duration(str(work.get("schedule_interval") or "每日"))
        return fmt_db(start), fmt_db(end)
    if mode == "continuous":
        return fmt_db(now), None
    return None, None


# 兼容旧调用名
def estimate_tracking_window(
    work: dict[str, Any], *, base: datetime | None = None
) -> tuple[str | None, str | None]:
    return estimate_waiting_window(work, base=base)


def estimate_running_end(
    work: dict[str, Any], *, started_at: datetime
) -> str | None:
    """进入 running 时写入 estimated_end_at；持续监控无预计结束。"""
    mode = str(work.get("schedule_mode") or "manual").strip()
    if mode == "continuous":
        return None
    if mode == "manual":
        return fmt_db(started_at + timedelta(hours=1))
    if mode == "scheduled":
        return fmt_db(started_at + timedelta(hours=1))
    if mode == "periodic":
        return fmt_db(started_at + _periodic_duration(str(work.get("schedule_interval") or "每日")))
    return fmt_db(started_at + timedelta(hours=1))


def resolve_publish_snapshot(
    work: dict[str, Any],
    *,
    now: datetime | None = None,
    earliest_execution_at: str | None = None,
) -> dict[str, str | None]:
    """发布入队时的初始追踪状态（不含 published_at）。"""
    clock = now or _now()
    mode = str(work.get("schedule_mode") or "manual").strip()
    est_start, est_end = estimate_waiting_window(work, base=clock)

    # 手动触发：始终等待，不写预计时间
    if mode == "manual":
        return {
            "queue_status": "waiting",
            "started_at": None,
            "estimated_start_at": None,
            "estimated_end_at": None,
        }

    # 持续监控：发布前已有执行记录 → 视为进行中，开始时间取最早事件
    if mode == "continuous" and earliest_execution_at:
        started = normalize_stored_at(earliest_execution_at) or earliest_execution_at
        parsed = parse_db_datetime(started) or clock
        return {
            "queue_status": "running",
            "started_at": started,
            "estimated_start_at": fmt_db(parsed),
            "estimated_end_at": None,
        }

    # 周期/定时：发布前已在当前预计窗口内执行过 → 回填真实开始
    if mode in ("periodic", "scheduled") and earliest_execution_at and est_start and est_end:
        exec_dt = parse_db_datetime(earliest_execution_at)
        win_start = parse_db_datetime(est_start)
        win_end = parse_db_datetime(est_end)
        if exec_dt and win_start and win_end and win_start <= exec_dt <= win_end:
            started = normalize_stored_at(earliest_execution_at) or earliest_execution_at
            return {
                "queue_status": "running",
                "started_at": started,
                "estimated_start_at": est_start,
                "estimated_end_at": est_end,
            }

    return {
        "queue_status": "waiting",
        "started_at": None,
        "estimated_start_at": est_start,
        "estimated_end_at": est_end,
    }


def validate_schedule_fields(
    schedule_mode: str,
    schedule_interval: str | None,
    schedule_times: str | None,
) -> None:
    mode = (schedule_mode or "manual").strip()
    if mode not in ("periodic", "scheduled", "continuous", "manual"):
        raise ValueError("schedule_mode 须为 periodic / scheduled / continuous / manual 之一")
    if mode == "periodic" and not (schedule_interval or "").strip():
        raise ValueError("周期检查须填写检查间隔（schedule_interval）")
    if mode == "scheduled" and not (schedule_times or "").strip():
        raise ValueError("定时检查须填写执行时刻（schedule_times）")

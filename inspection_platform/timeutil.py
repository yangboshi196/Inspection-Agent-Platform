"""平台时间：内部存 UTC ISO，展示用配置时区（默认 Asia/Shanghai）。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "Asia/Shanghai"


def platform_tz() -> ZoneInfo:
    name = (os.environ.get("SIA_TIMEZONE") or _DEFAULT_TZ).strip() or _DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_display_time(raw: str | None) -> str:
    """将 API 时间字段格式化为平台本地 `YYYY-MM-DD HH:MM:SS`。"""
    s = (raw or "").strip()
    if not s:
        return ""
    dt = _parse_api_datetime(s)
    if not dt:
        return s[:19] if len(s) >= 19 else s
    local = dt.astimezone(platform_tz())
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _parse_api_datetime(raw: str) -> datetime | None:
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # 历史数据：无时区标记的空格格式按 UTC 墙钟解析
            if "T" in s or "+" in s:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
        return dt
    except ValueError:
        return None

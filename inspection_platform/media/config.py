"""流媒体服务配置。"""

from __future__ import annotations

import os

from inspection_platform.envutil import env_first


def media_backend() -> str:
    """go2rtc | legacy（每连接 ffmpeg）。"""
    raw = env_first("SIA_MEDIA_BACKEND", "SIA_MEDIA_SERVER").strip().lower()
    if raw in ("legacy", "ffmpeg", "off", "none"):
        return "legacy"
    if raw in ("go2rtc", "media", "auto", ""):
        return "go2rtc"
    return raw


def go2rtc_api_base() -> str:
    return env_first("SIA_GO2RTC_API", "GO2RTC_API").strip() or "http://127.0.0.1:1984"


def go2rtc_rtsp_base() -> str:
    return env_first("SIA_GO2RTC_RTSP", "GO2RTC_RTSP").strip() or "rtsp://127.0.0.1:8554"


def go2rtc_public_api_prefix() -> str:
    """平台对外代理路径前缀（相对）。"""
    return "/api/media/go2rtc"

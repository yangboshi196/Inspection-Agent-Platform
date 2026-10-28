"""设备视频流地址规范化。"""

from __future__ import annotations

import re


def normalize_stream_url(addr: str) -> str | None:
    """将接入平台地址规范为 RTSP/HTTP URL。"""
    raw = (addr or "").strip()
    if not raw:
        return None
    if raw.startswith(("rtsp://", "http://", "https://")):
        return raw
    if re.match(r"^[\w.\-]+:\d+(?:/|$)", raw):
        return f"rtsp://{raw}"
    return None

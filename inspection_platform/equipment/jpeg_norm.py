"""JPEG 规范化：ffmpeg/go2rtc 直出可能带 Lavc 注释头，部分浏览器解码黑屏。"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def normalize_jpeg_bytes(data: bytes | None, *, min_size: int = 256) -> bytes | None:
    """转为标准 JFIF JPEG，便于浏览器 <img> 显示。"""
    raw = data if isinstance(data, bytes) else b""
    if len(raw) < min_size:
        return None
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(raw))
        im.load()
        out = io.BytesIO()
        im.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
        buf = out.getvalue()
        if len(buf) < min_size:
            return None
        return buf
    except Exception as exc:
        logger.warning("JPEG 规范化失败 len=%d: %s", len(raw), exc)
        return None

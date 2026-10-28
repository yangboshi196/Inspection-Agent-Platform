"""go2rtc HTTP API 客户端。"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import go2rtc_api_base

logger = logging.getLogger(__name__)


class Go2RtcClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base = (base_url or go2rtc_api_base()).rstrip("/")

    def is_alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/api/streams", timeout=2) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def patch_stream(self, name: str, src: str) -> None:
        q = urllib.parse.urlencode({"name": name, "src": src})
        req = urllib.request.Request(
            f"{self.base}/api/streams?{q}",
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status >= 400:
                    raise ValueError(f"go2rtc PATCH 失败 status={resp.status}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="ignore")[:200]
            raise ValueError(f"go2rtc 注册流失败: {body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"go2rtc 不可达: {exc.reason}") from exc

    def delete_stream(self, name: str) -> None:
        q = urllib.parse.urlencode({"src": name})
        req = urllib.request.Request(f"{self.base}/api/streams?{q}", method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=5)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            pass

    def api_stream_url(
        self,
        name: str,
        *,
        suffix: str,
        extra: dict[str, str] | None = None,
    ) -> str:
        """上游 go2rtc 拉流 URL（内网）。"""
        params: dict[str, str] = {"src": name}
        if extra:
            params.update(extra)
        q = urllib.parse.urlencode(params)
        return f"{self.base}/api/stream.{suffix}?{q}"

    def list_streams(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base}/api/streams", timeout=5) as resp:
            import json

            return json.loads(resp.read().decode())

    def grab_frame_jpeg(self, name: str, *, timeout: float = 10.0) -> bytes:
        """从已注册流抓取单帧 JPEG（不额外连接摄像机）。"""
        from inspection_platform.equipment.jpeg_norm import normalize_jpeg_bytes

        params = urllib.parse.urlencode(
            {"src": name, "timeout": str(max(1, int(timeout)))}
        )
        url = f"{self.base}/api/frame.jpeg?{params}"
        with urllib.request.urlopen(url, timeout=timeout + 5) as resp:
            return normalize_jpeg_bytes(resp.read()) or b""

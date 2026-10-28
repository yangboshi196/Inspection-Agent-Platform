"""流媒体桥接：摄像机 RTSP → go2rtc 单路拉流 → 多协议播放 / MP4 录像。"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.error
import urllib.parse
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from inspection_platform.equipment.rtsp_live import pick_stream_url
from inspection_platform.equipment.stream_url import normalize_stream_url

from .config import go2rtc_public_api_prefix, go2rtc_rtsp_base, media_backend
from .go2rtc_client import Go2RtcClient

logger = logging.getLogger(__name__)


def go2rtc_key_mode(stream_mode: str, quality: str = "hd") -> str:
    """go2rtc 流名后缀：平台统一主码流 _main（1080p）。"""
    return "main"


def stream_key(equipment_id: str, key_mode: str | None = None) -> str:
    eid = equipment_id.strip()
    raw = eid if eid.startswith("eq_") else f"eq_{eid}"
    if raw.endswith("_main") or raw.endswith("_sub"):
        return raw
    if key_mode in ("main", "sub"):
        return f"{raw}_{key_mode}"
    return raw


class MediaStreamService:
    def __init__(self) -> None:
        self._client = Go2RtcClient()

    def backend(self) -> str:
        """已配置 go2rtc 且 API 可达时走 go2rtc；不可达时回退 legacy 直连。"""
        if media_backend() != "go2rtc":
            return "legacy"
        if not self._client.is_alive():
            logger.warning("go2rtc API 暂不可达，回退 legacy 直连摄像机 RTSP")
            return "legacy"
        return "go2rtc"

    def _go2rtc_src(self, rtsp_url: str, stream_mode: str) -> str:
        """构造 go2rtc 源流：海康等需 TCP；H.265/H.264 copy 由浏览器 WebRTC 硬解。"""
        base = pick_stream_url(rtsp_url, stream="main")
        if "#" in base:
            return base
        return f"{base}#rtsp_transport=tcp"

    @staticmethod
    def _src_rtsp_base(url: str) -> str:
        raw = (url or "").split("#")[0].strip()
        if not raw:
            return ""
        return raw.lower()

    def _stream_info(self, key: str) -> dict[str, Any] | None:
        try:
            streams = self._client.list_streams()
        except (OSError, ValueError, urllib.error.URLError):
            return None
        info = streams.get(key) if isinstance(streams, dict) else None
        return info if isinstance(info, dict) else None

    def _producer_ready(self, key: str) -> bool:
        info = self._stream_info(key)
        if not info:
            return False
        producers = info.get("producers") or []
        if not producers:
            return False
        p0 = producers[0]
        return isinstance(p0, dict) and p0.get("id") is not None

    def producer_error(self, key: str) -> str:
        info = self._stream_info(key)
        if not info:
            return ""
        producers = info.get("producers") or []
        for p in producers:
            if not isinstance(p, dict):
                continue
            err = str(p.get("error") or "").strip()
            if err:
                return err
        return ""

    def producer_hint(self, key: str, rtsp_url: str) -> str:
        err = self.producer_error(key)
        if err:
            if "401" in err or "Unauthorized" in err:
                return "RTSP 认证失败，请检查用户名和密码"
            if "500" in err or "SETUP" in err:
                return "摄像机 RTSP 连接被拒绝（连接数已满或码流冲突）"
            if "timeout" in err.lower() or "timed out" in err.lower():
                return (
                    "拉流超时：请确认平台服务器能访问摄像机 IP"
                    "（浏览器能打开页面 ≠ 服务器能连 RTSP）"
                )
            return err[:240]
        host = ""
        try:
            host = urllib.parse.urlparse(rtsp_url.split("#")[0]).hostname or ""
        except ValueError:
            pass
        if host:
            return (
                f"go2rtc 无法从平台服务器连接 {host}，"
                "请检查网段/VLAN、防火墙与 RTSP 地址"
            )
        return "go2rtc 源流未就绪，请检查 RTSP 地址与 go2rtc 服务"

    def _wait_producer_ready(self, key: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            if self._producer_ready(key):
                return True
            time.sleep(0.25)
        return self._producer_ready(key)

    def prune_sub_stream(self, equipment_id: str) -> None:
        """主码流策略下释放 go2rtc 子码流，避免海康双连接占满 RTSP 会话。"""
        if self.backend() != "go2rtc":
            return
        self._client.delete_stream(stream_key(equipment_id, "sub"))

    def ensure_stream(
        self,
        equipment_id: str,
        rtsp_url: str,
        *,
        stream_mode: str = "auto",
        quality: str = "hd",
        wait_timeout: float = 15.0,
        max_attempts: int = 3,
    ) -> str:
        """在 go2rtc 注册/更新流；返回 stream key（含 _main/_sub 后缀）。"""
        if self.backend() != "go2rtc":
            return ""
        self.prune_sub_stream(equipment_id)
        key_mode = go2rtc_key_mode(stream_mode, quality)
        key = stream_key(equipment_id, key_mode)
        peer_key = stream_key(equipment_id, "sub" if key_mode == "main" else "main")
        # 主码流单路拉流：始终释放对端流，避免海康等设备双连接触发 SETUP 500
        if key_mode == "main":
            self._client.delete_stream(peer_key)
        elif self._producer_ready(peer_key):
            self._client.delete_stream(peer_key)
        mode_for_src = stream_mode if stream_mode != "auto" else key_mode
        src = self._go2rtc_src(rtsp_url, mode_for_src)
        info = self._stream_info(key)
        current_url = ""
        if info and isinstance(info.get("producers"), list) and info["producers"]:
            p0 = info["producers"][0]
            if isinstance(p0, dict):
                current_url = str(p0.get("url") or "")
        if self._producer_ready(key) and self._src_rtsp_base(current_url) == self._src_rtsp_base(src):
            return key
        if info:
            self._client.delete_stream(key)
            time.sleep(0.35)
        attempts = max(1, int(max_attempts))
        for attempt in range(attempts):
            self._client.patch_stream(key, src)
            if self._wait_producer_ready(key, timeout=wait_timeout):
                return key
            logger.warning(
                "go2rtc 源流未就绪 key=%s attempt=%d err=%s src=%s",
                key,
                attempt + 1,
                self.producer_error(key),
                src,
            )
            self._client.delete_stream(key)
            time.sleep(0.6)
        logger.warning(
            "go2rtc 源流注册失败 key=%s err=%s src=%s",
            key,
            self.producer_error(key),
            src,
        )
        return key

    def iter_flv_from_go2rtc(
        self,
        equipment_id: str,
        rtsp_url: str,
        *,
        stream_mode: str = "auto",
        quality: str = "hd",
        profile: str = "preview",
    ):
        """经 go2rtc 内网 RTSP 输出 H.264 FLV（不直连摄像机）。"""
        from inspection_platform.equipment.rtsp_flv import iter_flv_stream

        key_mode = go2rtc_key_mode(stream_mode, quality)
        self.ensure_stream(
            equipment_id, rtsp_url, stream_mode=stream_mode, quality=quality,
        )
        key = stream_key(equipment_id, key_mode)
        if not self._producer_ready(key):
            raise ValueError(f"go2rtc 源流未就绪 key={key}")
        rtsp_internal = self.internal_rtsp_url(equipment_id, key_mode=key_mode)
        return iter_flv_stream(
            rtsp_internal,
            stream="main" if key_mode == "main" else "sub",
            profile=profile,
        )

    def grab_frame_jpeg(
        self,
        equipment_id: str,
        rtsp_url: str,
        *,
        stream_mode: str = "main",
        quality: str = "hd",
        timeout: float = 10.0,
        wait_timeout: float = 4.0,
    ) -> bytes | None:
        """经 go2rtc 主码流抓帧，避免直连摄像机占用连接数。"""
        if self.backend() != "go2rtc":
            return None
        url = (rtsp_url or "").strip()
        if not url:
            return None
        try:
            self.ensure_stream(
                equipment_id,
                url,
                stream_mode=stream_mode,
                quality=quality,
                wait_timeout=wait_timeout,
            )
        except ValueError as exc:
            logger.warning("go2rtc 注册流失败 equipment=%s: %s", equipment_id, exc)
            return None
        key = stream_key(equipment_id, go2rtc_key_mode(stream_mode, quality))
        from inspection_platform.equipment.jpeg_norm import normalize_jpeg_bytes

        for attempt in range(3):
            if attempt and not self._producer_ready(key):
                self._wait_producer_ready(key, timeout=min(wait_timeout, 3.0))
            try:
                data = self._client.grab_frame_jpeg(key, timeout=timeout)
                normalized = normalize_jpeg_bytes(data)
                if normalized:
                    return normalized
            except Exception as exc:
                logger.warning(
                    "go2rtc 抓帧失败 equipment=%s attempt=%d: %s",
                    equipment_id,
                    attempt + 1,
                    exc,
                )
            time.sleep(0.35)
        return None

    def analysis_rtsp_url(self, equipment_id: str, camera_rtsp: str) -> str:
        """VAIO 等分析任务用内网 RTSP（go2rtc 主码流 1080p 单路拉流）。"""
        url = (camera_rtsp or "").strip()
        if not url:
            return url
        if self.backend() != "go2rtc":
            return url
        try:
            self.ensure_stream(equipment_id, url, stream_mode="main", quality="hd")
        except ValueError as exc:
            logger.warning(
                "go2rtc 注册流失败 equipment=%s，回退直连 RTSP: %s",
                equipment_id,
                exc,
            )
            return url
        return self.internal_rtsp_url(equipment_id, key_mode="main")

    def internal_rtsp_url(self, equipment_id: str, *, key_mode: str = "main") -> str:
        key = stream_key(equipment_id, key_mode)
        base = go2rtc_rtsp_base().rstrip("/")
        return f"{base}/{key}"

    def play_urls(
        self,
        equipment_id: str,
        *,
        stream_mode: str = "auto",
        quality: str = "hd",
    ) -> dict[str, Any]:
        eid = equipment_id.strip()
        mode = "main"
        q = "hd"
        backend = self.backend()
        base = f"/api/equipment/{urllib.parse.quote(eid, safe='')}/live"
        common = "stream=main&quality=hd"
        mjpeg_qs = common
        if backend == "go2rtc":
            key_mode = go2rtc_key_mode(mode, q)
            key = stream_key(eid, key_mode)
            return {
                "backend": "go2rtc",
                "stream_key": key,
                "stream_mode": mode,
                "quality": q,
                "webrtc": f"{base}/webrtc/embed?{common}",
                "hls": f"{base}/hls/stream.m3u8?{common}",
                "flv": f"{base}/flv?{common}",
                "mp4": f"{base}/mp4?{common}",
                "mjpeg": f"{base}/mjpeg?{mjpeg_qs}",
                "snapshot": f"{base}/snapshot?{common}",
                "rtsp_internal": self.internal_rtsp_url(eid, key_mode=key_mode),
            }
        return {
            "backend": "legacy",
            "stream_mode": mode,
            "quality": q,
            "webrtc": None,
            "hls": None,
            "flv": f"{base}/flv?{common}",
            "mp4": None,
            "mjpeg": f"{base}/mjpeg?{mjpeg_qs}",
            "snapshot": f"{base}/snapshot?{common}",
            "rtsp_internal": None,
        }

    def go2rtc_upstream(
        self,
        equipment_id: str,
        suffix: str,
        query: dict[str, str],
        *,
        stream_mode: str = "auto",
        quality: str = "hd",
    ) -> str:
        key_mode = go2rtc_key_mode(stream_mode, quality)
        key = stream_key(equipment_id, key_mode)
        extra = {k: v for k, v in query.items() if k not in ("src", "stream", "quality", "preview_rtsp")}
        return self._client.api_stream_url(key, suffix=suffix, extra=extra or None)

    async def proxy_stream(self, upstream_url: str) -> AsyncIterator[bytes]:
        timeout = httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", upstream_url) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise ValueError(body.decode(errors="ignore")[:300] or f"upstream {resp.status_code}")
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

    def record_mp4(
        self,
        equipment_id: str,
        dest: Path,
        *,
        duration_sec: float = 30.0,
        stream_mode: str = "main",
    ) -> Path:
        """从 go2rtc 内网 RTSP 旁路录像（H.264 copy，无二次编码）。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        key_mode = go2rtc_key_mode(stream_mode, "hd")
        rtsp = self.internal_rtsp_url(equipment_id, key_mode=key_mode)
        dur = max(1.0, min(float(duration_sec), 600.0))
        ffmpeg = (os.environ.get("SIA_FFMPEG") or "").strip() or "ffmpeg"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp,
            "-t",
            f"{dur:.3f}",
            "-an",
            "-c:v",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=int(dur) + 120, check=False)
        if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1024:
            err = proc.stderr.decode(errors="ignore")[:300]
            raise ValueError(err or "录像失败")
        return dest


@lru_cache
def get_media_service() -> MediaStreamService:
    return MediaStreamService()

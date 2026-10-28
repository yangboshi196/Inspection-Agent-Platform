"""jellyfin-ffmpeg NVDEC 硬解长连接读帧（hevc_cuvid / h264_cuvid）。"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from inspection_platform.equipment.rtsp_live import _ffmpeg_bin, _ffmpeg_has_cuvid, _ffmpeg_socket_timeout_args, _hwaccel_enabled


def nvdec_available() -> bool:
    return _hwaccel_enabled() and _ffmpeg_has_cuvid()


def _nvdec_stream_cmd(rtsp_url: str, *, decoder: str) -> list[str]:
    return [
        _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        *_ffmpeg_socket_timeout_args(),
        "-hwaccel",
        "cuda",
        "-c:v",
        decoder,
        "-i",
        rtsp_url,
        "-an",
        "-sn",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-f",
        "mjpeg",
        "-",
    ]


def _split_jpeg(buf: bytes) -> tuple[bytes | None, bytes]:
    start = buf.find(b"\xff\xd8")
    if start < 0:
        return None, buf[-1:] if buf else b""
    end = buf.find(b"\xff\xd9", start + 2)
    if end < 0:
        return None, buf[start:]
    return buf[start : end + 2], buf[end + 2 :]


class NvdecFrameReader:
    """ffmpeg NVDEC 子进程持续输出 MJPEG，后台线程解析最新帧。"""

    def __init__(self, rtsp_url: str) -> None:
        if not nvdec_available():
            raise RuntimeError("NVDEC 不可用（需 SIA_RTSP_HWACCEL=cuda 与 jellyfin-ffmpeg）")
        self.rtsp_url = rtsp_url
        self._jpeg: bytes | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> NvdecFrameReader:
        if self._started:
            return self
        self._started = True
        decoders = ["hevc_cuvid", "h264_cuvid"]
        last_err = ""
        for decoder in decoders:
            cmd = _nvdec_stream_cmd(self.rtsp_url, decoder=decoder)
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as e:
                last_err = str(e)
                continue
            if proc.stdout is None:
                proc.kill()
                continue
            self._proc = proc
            self._thread = threading.Thread(target=self._pump, daemon=True)
            self._thread.start()
            return self
        self._started = False
        raise ValueError(last_err or "无法启动 NVDEC ffmpeg 进程")

    def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        buf = b""
        while self._started:
            chunk = self._proc.stdout.read(16384)
            if not chunk:
                if self._proc.poll() is not None:
                    break
                continue
            buf += chunk
            while True:
                frame, buf = _split_jpeg(buf)
                if frame is None:
                    break
                with self._lock:
                    self._jpeg = frame

    def read_jpeg(self, *, quality: int = 80) -> bytes | None:
        del quality  # NVDEC 路径已由 ffmpeg 编码 MJPEG
        with self._lock:
            return self._jpeg

    def stop(self) -> None:
        self._started = False
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

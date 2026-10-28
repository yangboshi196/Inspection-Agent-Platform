"""RTSP 预览长连接池：复用读帧线程，避免每次 snapshot 重连（帧率/延迟关键优化）。"""

from __future__ import annotations

import atexit
import os
import threading
import time
from typing import Any, Protocol

_IDLE_SEC = float(os.environ.get("SIA_RTSP_POOL_IDLE_SEC", "90"))


class _FrameSource(Protocol):
    def start(self) -> Any: ...
    def read_jpeg(self, *, quality: int = 80) -> bytes | None: ...
    def stop(self) -> None: ...


class _PooledEntry:
    __slots__ = ("reader", "last_access", "url")

    def __init__(self, reader: _FrameSource, url: str) -> None:
        self.reader = reader
        self.url = url
        self.last_access = time.monotonic()


_pool: dict[str, _PooledEntry] = {}
_pool_lock = threading.Lock()


def _reader_backend() -> str:
    return (os.environ.get("SIA_RTSP_READER") or "auto").strip().lower()


def _create_reader(rtsp_url: str) -> _FrameSource:
    from inspection_platform.equipment.rtsp_nvdec import NvdecFrameReader, nvdec_available

    if nvdec_available():
        try:
            return NvdecFrameReader(rtsp_url).start()
        except Exception:
            pass

    backend = _reader_backend()
    if backend == "pyav":
        from inspection_platform.equipment.rtsp_pyav import PyAvFrameReader

        return PyAvFrameReader(rtsp_url).start()

    from inspection_platform.equipment.rtsp_opencv import RtspFrameReader, opencv_available

    if backend == "opencv" or (backend == "auto" and opencv_available()):
        try:
            return RtspFrameReader(rtsp_url).start()
        except Exception:
            if backend == "opencv":
                raise

    from inspection_platform.equipment.rtsp_pyav import PyAvFrameReader

    return PyAvFrameReader(rtsp_url).start()


def _evict_idle_locked(now: float) -> None:
    stale = [k for k, e in _pool.items() if now - e.last_access > _IDLE_SEC]
    for key in stale:
        entry = _pool.pop(key, None)
        if entry:
            entry.reader.stop()


def get_pooled_jpeg(rtsp_url: str, *, wait_sec: float = 2.5, quality: int = 80) -> bytes | None:
    """从长连接池取最新 JPEG；已连接时通常 <100ms。"""
    now = time.monotonic()
    with _pool_lock:
        _evict_idle_locked(now)
        entry = _pool.get(rtsp_url)
        if entry is None:
            try:
                reader = _create_reader(rtsp_url)
            except Exception:
                return None
            entry = _PooledEntry(reader, rtsp_url)
            _pool[rtsp_url] = entry
        entry.last_access = now
        reader = entry.reader

    deadline = now + wait_sec
    while time.monotonic() < deadline:
        jpeg = reader.read_jpeg(quality=quality)
        if jpeg:
            with _pool_lock:
                if rtsp_url in _pool:
                    _pool[rtsp_url].last_access = time.monotonic()
            return jpeg
        time.sleep(0.03)
    return None


def release_pool() -> None:
    with _pool_lock:
        for entry in _pool.values():
            entry.reader.stop()
        _pool.clear()


atexit.register(release_pool)

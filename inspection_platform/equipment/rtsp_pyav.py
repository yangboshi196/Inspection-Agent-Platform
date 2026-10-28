"""PyAV 解码 RTSP 帧（thread_type AUTO + 丢帧，HEVC 主码流更稳）。"""

from __future__ import annotations

import os
import threading
from typing import Any

_PYAV: Any | None = None
_CV2: Any | None = None


def pyav_available() -> bool:
    global _PYAV, _CV2
    if _PYAV is not None:
        return _PYAV is not False
    try:
        import av  # noqa: PLC0415
        import cv2  # noqa: PLC0415

        _PYAV = av
        _CV2 = cv2
        return True
    except ImportError:
        _PYAV = False
        _CV2 = False
        return False


def _rtsp_open_options(*, hwaccel: str | None = None) -> dict[str, str]:
    opts: dict[str, str] = {
        "rtsp_transport": "tcp",
        "stimeout": "8000000",
        "buffer_size": "512000",
        "fflags": "nobuffer",
    }
    if hwaccel:
        opts["hwaccel"] = hwaccel
    return opts


def _configure_stream(stream: Any) -> None:
    try:
        stream.thread_type = "AUTO"
    except Exception:
        pass


def _frame_to_jpeg(frame: Any, *, quality: int = 80) -> bytes:
    import cv2  # noqa: PLC0415

    img = frame.to_ndarray(format="bgr24")
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG 编码失败")
    return buf.tobytes()


def capture_jpeg_pyav(
    rtsp_url: str,
    *,
    timeout_sec: float = 20.0,
    hwaccel: str | None = None,
    discard_frames: int = 3,
) -> bytes:
    """PyAV demux/decode；解码慢时丢弃中间帧，只编码最新帧。"""
    if not pyav_available():
        raise RuntimeError("PyAV/opencv 未安装")

    import av  # noqa: PLC0415

    options = _rtsp_open_options(hwaccel=hwaccel)
    container = av.open(rtsp_url, options=options, timeout=float(timeout_sec))
    try:
        stream = container.streams.video[0]
        _configure_stream(stream)
        latest: Any | None = None
        for packet in container.demux(stream):
            for frame in packet.decode():
                latest = frame
                if discard_frames <= 0:
                    return _frame_to_jpeg(latest)
                discard_frames -= 1
        if latest is not None:
            return _frame_to_jpeg(latest)
        raise ValueError("RTSP 流中未收到可解码视频帧")
    finally:
        container.close()


def capture_jpeg_pyav_auto(rtsp_url: str, *, timeout_sec: float = 20.0) -> tuple[bytes | None, str]:
    """按环境变量尝试 PyAV；失败返回 (None, 错误信息)。"""
    if not pyav_available():
        return None, "PyAV 未安装"

    hw = (os.environ.get("SIA_RTSP_HWACCEL") or "").strip()
    if hw:
        try:
            return capture_jpeg_pyav(rtsp_url, timeout_sec=timeout_sec, hwaccel=hw), ""
        except Exception as e:
            if hw.lower() not in {"0", "false", "off", "none"}:
                try:
                    return capture_jpeg_pyav(rtsp_url, timeout_sec=timeout_sec), ""
                except Exception as e2:
                    return None, str(e2)
            return None, str(e)

    try:
        return capture_jpeg_pyav(rtsp_url, timeout_sec=timeout_sec), ""
    except Exception as e:
        return None, str(e)


class PyAvFrameReader:
    """PyAV 后台线程持续解码，只保留最新帧（低延迟 MJPEG / 连接池）。"""

    def __init__(self, rtsp_url: str) -> None:
        if not pyav_available():
            raise RuntimeError("PyAV 未安装")
        self.rtsp_url = rtsp_url
        self._frame: Any | None = None
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._container: Any | None = None

    def start(self) -> PyAvFrameReader:
        if self._started:
            return self
        import av  # noqa: PLC0415

        self._started = True
        self._container = av.open(self.rtsp_url, options=_rtsp_open_options())
        stream = self._container.streams.video[0]
        _configure_stream(stream)
        self._thread = threading.Thread(target=self._update, args=(stream,), daemon=True)
        self._thread.start()
        return self

    def _update(self, stream: Any) -> None:
        assert self._container is not None
        try:
            for frame in self._container.decode(stream):
                if not self._started:
                    break
                img = frame.to_ndarray(format="bgr24")
                with self._lock:
                    self._frame = img
        except Exception:
            pass

    def read(self) -> Any | None:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def read_jpeg(self, *, quality: int = 80) -> bytes | None:
        frame = self.read()
        if frame is None:
            return None
        import cv2  # noqa: PLC0415

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        return buf.tobytes()

    def stop(self) -> None:
        self._started = False
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

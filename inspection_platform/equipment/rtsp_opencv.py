"""OpenCV VideoCapture 拉取 RTSP（低缓冲 + grab/retrieve 跳帧 + 多线程读帧）。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

_CV2: Any | None = None
_FFMPEG_OPTS_SET = False

_GRAB_BURST = int(os.environ.get("SIA_RTSP_GRAB_BURST", "12"))


def _ensure_ffmpeg_options() -> None:
    global _FFMPEG_OPTS_SET
    if _FFMPEG_OPTS_SET:
        return
    # 须在首次 VideoCapture 前设置
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        "rtsp_transport;tcp|stimeout;8000000|max_delay;0|fflags;nobuffer",
    )
    _FFMPEG_OPTS_SET = True


def opencv_available() -> bool:
    global _CV2
    if _CV2 is not None:
        return _CV2 is not False
    try:
        import cv2  # noqa: PLC0415

        _CV2 = cv2
        return True
    except ImportError:
        _CV2 = False
        return False


def _open_capture(rtsp_url: str) -> Any:
    import cv2  # noqa: PLC0415

    _ensure_ffmpeg_options()
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def _drain_latest_frame(cap: Any, *, max_grab: int | None = None) -> tuple[bool, Any | None]:
    """grab 快速跳帧，最后一次 retrieve 解码，避免 read() 阻塞堆积。"""
    burst = max_grab if max_grab is not None else _GRAB_BURST
    grabbed = False
    for _ in range(max(1, burst)):
        if cap.grab():
            grabbed = True
    if not grabbed:
        return False, None
    return cap.retrieve()


def _frame_to_jpeg(frame: Any, *, quality: int = 80) -> bytes:
    import cv2  # noqa: PLC0415

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG 编码失败")
    return buf.tobytes()


def capture_jpeg_opencv(
    rtsp_url: str,
    *,
    timeout_sec: float = 20.0,
    discard_buffered: int | None = None,
) -> bytes:
    """OpenCV 拉流首帧（grab 跳帧 + 只 decode 最新帧）。"""
    if not opencv_available():
        raise RuntimeError("OpenCV 未安装")

    cap = _open_capture(rtsp_url)
    if not cap.isOpened():
        raise ValueError("OpenCV 无法打开 RTSP 流")

    deadline = time.monotonic() + timeout_sec
    last_err = ""
    burst = discard_buffered if discard_buffered is not None else _GRAB_BURST
    try:
        while time.monotonic() < deadline:
            ret, frame = _drain_latest_frame(cap, max_grab=burst)
            if ret and frame is not None and getattr(frame, "size", 0) > 0:
                return _frame_to_jpeg(frame)
            last_err = "无法读取视频帧"
            time.sleep(0.05)
        raise ValueError(last_err or "OpenCV 拉流超时")
    finally:
        cap.release()


def capture_jpeg_opencv_auto(rtsp_url: str, *, timeout_sec: float = 20.0) -> tuple[bytes | None, str]:
    if not opencv_available():
        return None, "OpenCV 未安装"
    try:
        return capture_jpeg_opencv(rtsp_url, timeout_sec=timeout_sec), ""
    except Exception as e:
        return None, str(e)


class RtspFrameReader:
    """独立线程持续读流，grab 跳帧后只保留最新一帧。"""

    def __init__(self, rtsp_url: str) -> None:
        if not opencv_available():
            raise RuntimeError("OpenCV 未安装")
        self.rtsp_url = rtsp_url
        self._cap: Any | None = None
        self._frame: Any | None = None
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> RtspFrameReader:
        if self._started:
            return self
        self._started = True
        self._cap = _open_capture(self.rtsp_url)
        if not self._cap.isOpened():
            self._started = False
            raise ValueError("OpenCV 无法打开 RTSP 流")
        self._thread = threading.Thread(target=self._update, daemon=True)
        self._thread.start()
        return self

    def _update(self) -> None:
        while self._started and self._cap is not None:
            ret, frame = _drain_latest_frame(self._cap)
            if not ret or frame is None:
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame

    def read(self) -> Any | None:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def read_jpeg(self, *, quality: int = 80) -> bytes | None:
        frame = self.read()
        if frame is None:
            return None
        return _frame_to_jpeg(frame, quality=quality)

    def stop(self) -> None:
        self._started = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

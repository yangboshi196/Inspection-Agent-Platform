"""RTSP 实时预览：ffmpeg 抓帧 / MJPEG 推流。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterator

MJPEG_BOUNDARY = "siaframe"


def _ffmpeg_bin() -> str:
    custom = (os.environ.get("SIA_FFMPEG") or "").strip()
    if custom:
        return custom
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffmpeg_resolvable() -> bool:
    path = _ffmpeg_bin()
    return os.path.isfile(path) or shutil.which(path) is not None


def _hwaccel_enabled() -> bool:
    v = (os.environ.get("SIA_RTSP_HWACCEL") or "").strip().lower()
    return v not in ("", "0", "false", "off", "none", "soft", "cpu")


def _ffmpeg_has_cuvid(ffmpeg_bin: str | None = None) -> bool:
    bin_path = ffmpeg_bin or _ffmpeg_bin()
    try:
        proc = subprocess.run(
            [bin_path, "-hide_banner", "-decoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = proc.stdout or ""
    return "hevc_cuvid" in out or "h264_cuvid" in out


def _is_jpeg(data: bytes) -> bool:
    return len(data) > 256 and data[:2] == b"\xff\xd8" and b"\xff\xd9" in data[-4:]


def _hikvision_substream(url: str) -> str | None:
    """海康主码流 101/201 → 子码流 102/202。"""
    m = re.search(r"/Streaming/Channels/(\d+)", url)
    if not m:
        return None
    n = int(m.group(1))
    if n % 10 != 1:
        return None
    return url[: m.start(1)] + str(n + 1) + url[m.end(1) :]


def _prefer_substream() -> bool:
    """平台统一主码流 1080p；仅显式 SIA_RTSP_PREFER_SUB=1 时允许子码流。"""
    v = (os.environ.get("SIA_RTSP_PREFER_SUB") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _preview_url_candidates(rtsp_url: str) -> list[str]:
    """预览 URL 列表；默认主码流 /101（1080p）。"""
    return stream_url_candidates(rtsp_url, prefer_sub=_prefer_substream())


def stream_url_candidates(rtsp_url: str, *, prefer_sub: bool = False) -> list[str]:
    """按主/子码流偏好返回 RTSP URL 候选列表（海康 /101 ↔ /102）。"""
    sub = _hikvision_substream(rtsp_url)
    if sub and sub != rtsp_url:
        if prefer_sub:
            return [sub, rtsp_url]
        return [rtsp_url, sub]
    out = [rtsp_url]
    if sub and sub not in out:
        out.append(sub)
    return out


def pick_stream_url(rtsp_url: str, *, stream: str = "auto") -> str:
    """stream: auto | main → 主码流；sub 亦映射为主码流（平台禁止子码流预览/取证）。"""
    mode = (stream or "auto").strip().lower()
    if mode in ("auto", "sub"):
        mode = "main"
    if mode == "main":
        return stream_url_candidates(rtsp_url, prefer_sub=False)[0]
    return stream_url_candidates(rtsp_url, prefer_sub=_prefer_substream())[0]


def _ffmpeg_socket_timeout_args() -> list[str]:
    """jellyfin-ffmpeg 7.x 用 -timeout；系统旧版 ffmpeg 用 -stimeout。"""
    if os.environ.get("SIA_FFMPEG") or _ffmpeg_has_cuvid():
        return ["-timeout", "8000000"]
    return ["-stimeout", "8000000"]


def _ffmpeg_snapshot_cmd(rtsp_url: str, *, ffmpeg_bin: str | None = None) -> list[str]:
    return [
        ffmpeg_bin or _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        *_ffmpeg_socket_timeout_args(),
        "-probesize",
        "5000000",
        "-analyzeduration",
        "5000000",
        "-i",
        rtsp_url,
        "-an",
        "-sn",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-",
    ]


def _ffmpeg_cuda_snapshot_cmd(rtsp_url: str, *, decoder: str, ffmpeg_bin: str | None = None) -> list[str]:
    """NVDEC 硬解单帧（需 jellyfin-ffmpeg 等带 cuvid 的版本）。"""
    return [
        ffmpeg_bin or _ffmpeg_bin(),
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
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-",
    ]


def _capture_ffmpeg_jpeg(
    rtsp_url: str,
    *,
    timeout_sec: int,
    cuda: bool = False,
) -> tuple[bytes | None, str]:
    ffmpeg_bin = _ffmpeg_bin()
    decoders = ["hevc_cuvid", "h264_cuvid"] if cuda else [None]
    last_err = ""
    for decoder in decoders:
        if decoder is None:
            cmd = _ffmpeg_snapshot_cmd(rtsp_url, ffmpeg_bin=ffmpeg_bin)
        else:
            if cuda and not _ffmpeg_has_cuvid(ffmpeg_bin):
                return None, "当前 ffmpeg 无 hevc_cuvid/h264_cuvid，请运行 scripts/install-rtsp-nvdec-SIA_agent.sh"
            cmd = _ffmpeg_cuda_snapshot_cmd(rtsp_url, decoder=decoder, ffmpeg_bin=ffmpeg_bin)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec, check=False)
        except subprocess.TimeoutExpired:
            return None, "拉取 RTSP 画面超时"
        stderr = proc.stderr.decode(errors="ignore").strip()
        if _is_jpeg(proc.stdout):
            return proc.stdout, ""
        last_err = stderr
        if not cuda:
            break
    return None, last_err


def _capture_jpeg_once(rtsp_url: str, *, timeout_sec: int) -> tuple[bytes | None, str]:
    return _capture_ffmpeg_jpeg(rtsp_url, timeout_sec=timeout_sec, cuda=False)


def _friendly_error(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "ffmpeg 抓帧失败"
    if "500 Internal Server Error" in text or "5XX Server Error" in text:
        return "摄像头 RTSP 连接被拒绝（可能连接数已满），请关闭其他占流页面后重试"
    if "VPS 0 does not exist" in text or "SPS 0 does not exist" in text:
        return "主码流 H.265 解码异常，请确认 jellyfin-ffmpeg / NVDEC 或检查摄像机编码配置"
    if "Connection refused" in text:
        return "无法连接 RTSP 端口，请确认设备在线且 554 已开启"
    if "401" in text or "Unauthorized" in text:
        return "RTSP 认证失败，请检查用户名和密码"
    return text[:200]


def grab_rtsp_snapshot(rtsp_url: str, *, timeout_sec: int = 20, stream: str = "auto") -> bytes:
    """从 RTSP 拉取单帧 JPEG；stream=main 用于取证对齐主码流，auto 默认预览策略。"""
    from inspection_platform.equipment.rtsp_opencv import capture_jpeg_opencv_auto, opencv_available
    from inspection_platform.equipment.rtsp_preview_pool import get_pooled_jpeg
    from inspection_platform.equipment.rtsp_pyav import capture_jpeg_pyav_auto, pyav_available

    use_cuda = _hwaccel_enabled() and _ffmpeg_has_cuvid()
    use_opencv = opencv_available() and not use_cuda
    use_pyav = pyav_available() and not use_cuda

    mode = (stream or "auto").strip().lower()
    candidates = [pick_stream_url(rtsp_url, stream="main")]
    last_err = ""

    for url in candidates:
        pooled = get_pooled_jpeg(url, wait_sec=min(4.0, float(timeout_sec)))
        if pooled:
            return pooled

        for attempt in range(3):
            if use_cuda:
                data, err = _capture_ffmpeg_jpeg(url, timeout_sec=timeout_sec, cuda=True)
                if data:
                    return data
                if err:
                    last_err = err
            if use_opencv:
                data, err = capture_jpeg_opencv_auto(url, timeout_sec=float(timeout_sec))
                if data:
                    return data
                if err:
                    last_err = err
            if use_pyav:
                data, err = capture_jpeg_pyav_auto(url, timeout_sec=float(timeout_sec))
                if data:
                    return data
                if err:
                    last_err = err
            data, stderr = _capture_jpeg_once(url, timeout_sec=timeout_sec)
            if data:
                return data
            if stderr:
                last_err = stderr
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))

    if not opencv_available() and not pyav_available() and not _ffmpeg_resolvable():
        raise ValueError("请安装 OpenCV/PyAV 或 ffmpeg 以预览 RTSP（见 scripts/install-rtsp-nvdec-SIA_agent.sh）")
    from inspection_platform.equipment.jpeg_norm import normalize_jpeg_bytes

    normalized = normalize_jpeg_bytes(data)
    if not normalized:
        raise ValueError(_friendly_error(last_err))
    return normalized


def _mjpeg_allow_scale_filter() -> str:
    """Optional downscale for bandwidth; off by default (keep 1080p main stream)."""
    scale = (os.environ.get("SIA_MJPEG_ALLOW_SCALE") or "").strip()
    return scale if scale else ""


def _ffmpeg_stream_cmd(rtsp_url: str, *, fps: int) -> list[str]:
    out = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        *_ffmpeg_socket_timeout_args(),
        "-probesize",
        "5000000",
        "-analyzeduration",
        "5000000",
        "-i",
        rtsp_url,
        "-an",
        "-sn",
    ]
    scale = _mjpeg_allow_scale_filter()
    if scale:
        out.extend(["-vf", f"scale={scale}"])
    out.extend(
        [
            "-c:v",
            "mjpeg",
            "-q:v",
            "5",
            "-r",
            str(fps),
            "-f",
            "mjpeg",
            "-",
        ]
    )
    return out


def iter_mjpeg_multipart(rtsp_url: str, *, fps: int = 10) -> Iterator[bytes]:
    """持续从 RTSP 转 MJPEG，供 multipart/x-mixed-replace 实时预览。"""
    fps = max(1, min(fps, 15))
    interval = 1.0 / fps

    from inspection_platform.equipment.rtsp_preview_pool import get_pooled_jpeg

    boundary = MJPEG_BOUNDARY.encode()
    stream_url = pick_stream_url(rtsp_url, stream="main")
    first = True
    while True:
        wait = interval + (3.0 if first else 0.5)
        jpeg = get_pooled_jpeg(stream_url, wait_sec=wait)
        first = False
        if jpeg:
            yield (
                b"--"
                + boundary
                + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
        time.sleep(interval)

"""RTSP → HTTP-FLV 直播流（供 XGPlayer / flv.js 等企业播放器）。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator

from inspection_platform.equipment.rtsp_live import (
    _ffmpeg_bin,
    _ffmpeg_has_cuvid,
    _ffmpeg_socket_timeout_args,
    _ffmpeg_resolvable,
    _hwaccel_enabled,
    pick_stream_url,
    stream_url_candidates,
)

logger = logging.getLogger(__name__)

_FIRST_BYTE_TIMEOUT_SEC = float(os.environ.get("SIA_RTSP_FLV_FIRST_BYTE_SEC", "8"))


def _env_kbps(name: str, default: str) -> str:
    raw = (os.environ.get(name) or default).strip()
    if raw and not raw.lower().endswith("k"):
        return f"{raw}k"
    return raw


def _flv_video_encoder() -> str:
    enc = (os.environ.get("SIA_RTSP_FLV_ENCODER") or "libx264").strip().lower()
    if enc in ("nvenc", "h264_nvenc"):
        if shutil.which(_ffmpeg_bin()) or os.path.isfile(_ffmpeg_bin()):
            try:
                proc = subprocess.run(
                    [_ffmpeg_bin(), "-hide_banner", "-encoders"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if "h264_nvenc" in (proc.stdout or ""):
                    return "h264_nvenc"
            except (OSError, subprocess.TimeoutExpired):
                pass
        return "libx264"
    return "libx264"


def _flv_output_args(profile: str = "preview") -> list[str]:
    """FLV 容器需 H.264；profile=hd 用于详情/全屏，preview 用于宫格。"""
    hd = (profile or "preview").strip().lower() == "hd"
    if hd:
        preset = os.environ.get("SIA_RTSP_FLV_HD_PRESET", "veryfast")
        bitrate = _env_kbps("SIA_RTSP_FLV_HD_BITRATE", "2500")
        bufsize = _env_kbps("SIA_RTSP_FLV_HD_BUFSIZE", "5000")
        scale = (os.environ.get("SIA_RTSP_FLV_HD_SCALE") or "").strip()
        gop = (os.environ.get("SIA_RTSP_FLV_HD_GOP") or "50").strip()
    else:
        preset = os.environ.get("SIA_RTSP_FLV_PRESET", "ultrafast")
        bitrate = _env_kbps("SIA_RTSP_FLV_BITRATE", "800")
        bufsize = _env_kbps("SIA_RTSP_FLV_BUFSIZE", "1600")
        scale = (os.environ.get("SIA_RTSP_FLV_SCALE") or "").strip()
        gop = (os.environ.get("SIA_RTSP_FLV_GOP") or "30").strip()

    encoder = _flv_video_encoder()
    out: list[str] = ["-an"]
    if scale:
        out.extend(["-vf", f"scale={scale}"])
    out.extend(["-c:v", encoder])
    if encoder == "h264_nvenc":
        out.extend(
            [
                "-preset",
                os.environ.get("SIA_RTSP_FLV_NVENC_PRESET", "p4"),
                "-tune",
                "ll",
                "-profile:v",
                "main",
            ]
        )
    else:
        out.extend(
            [
                "-preset",
                preset,
                "-tune",
                "zerolatency",
                "-profile:v",
                "main",
            ]
        )
    out.extend(
        [
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            bufsize,
            "-g",
            gop,
            "-f",
            "flv",
            "-",
        ]
    )
    return out


def _ffmpeg_flv_cmd(
    rtsp_url: str,
    *,
    cuda_decoder: str | None = None,
    profile: str = "preview",
) -> list[str]:
    head = [
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
    ]
    if cuda_decoder:
        head.extend(["-hwaccel", "cuda", "-c:v", cuda_decoder])
    head.extend(["-i", rtsp_url])
    return head + _flv_output_args(profile)


def _pick_flv_cmds(rtsp_url: str, *, profile: str = "preview") -> list[list[str]]:
    cmds: list[list[str]] = []
    if _hwaccel_enabled() and _ffmpeg_has_cuvid():
        for decoder in ("h264_cuvid", "hevc_cuvid"):
            cmds.append(_ffmpeg_flv_cmd(rtsp_url, cuda_decoder=decoder, profile=profile))
    cmds.append(_ffmpeg_flv_cmd(rtsp_url, profile=profile))
    return cmds


def _read_stderr_tail(proc: subprocess.Popen[bytes]) -> str:
    if proc.stderr is None:
        return ""
    try:
        raw = proc.stderr.read()
        return raw.decode(errors="ignore").strip()[:300]
    except OSError:
        return ""


def _iter_flv_from_cmd(cmd: list[str]) -> Iterator[bytes]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not proc.stdout:
        proc.kill()
        raise ValueError("无法启动 FLV 转码进程")

    first_byte: bytes | None = None
    err_tail = ""
    lock = threading.Lock()
    done = threading.Event()

    def wait_first() -> None:
        nonlocal first_byte, err_tail
        try:
            chunk = proc.stdout.read(1)
            with lock:
                first_byte = chunk
            if not chunk:
                err_tail = _read_stderr_tail(proc)
        finally:
            done.set()

    waiter = threading.Thread(target=wait_first, daemon=True)
    waiter.start()
    if not done.wait(timeout=_FIRST_BYTE_TIMEOUT_SEC):
        proc.kill()
        raise ValueError("FLV 转码首帧超时，请检查 RTSP 地址与网络")
    waiter.join(timeout=0.1)

    with lock:
        if not first_byte:
            msg = err_tail or "ffmpeg 未输出 FLV 数据"
            raise ValueError(msg)
        lead = first_byte

    yield lead
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                if proc.poll() is not None:
                    err_tail = _read_stderr_tail(proc)
                    if err_tail:
                        logger.warning("FLV 转码进程结束: %s", err_tail)
                    break
                continue
            yield chunk
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def iter_flv_stream(
    rtsp_url: str,
    *,
    stream: str = "auto",
    profile: str = "preview",
) -> Iterator[bytes]:
    """持续将 RTSP 转为 FLV 字节流。stream=main 拉主码流；profile=hd 提高码率与编码质量。"""
    if not _ffmpeg_resolvable():
        raise ValueError("未安装 ffmpeg，无法输出 FLV 直播流")

    main_url = pick_stream_url(rtsp_url, stream="main")
    urls = [main_url]

    last_err = ""
    for url in urls:
        for cmd in _pick_flv_cmds(url, profile=profile):
            try:
                for chunk in _iter_flv_from_cmd(cmd):
                    yield chunk
                return
            except ValueError as exc:
                last_err = str(exc)
                logger.warning("FLV 转码失败 url=%s err=%s", url, last_err)
                continue

    raise ValueError(last_err or "无法从 RTSP 输出 FLV，请检查地址、账号与码流")

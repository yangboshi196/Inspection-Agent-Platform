"""巡检事件检测取证：保存与展示对齐的抓拍帧与证据片段。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from inspection_platform.app.config import get_settings

logger = logging.getLogger(__name__)

_EVIDENCE_SUBDIR = "inspection_event_evidence"

# 取证 / 大模型检测：仅主码流 1080p（拒绝 720p 子码流）
MAIN_HD_MIN_WIDTH = 1280
MAIN_HD_MIN_HEIGHT = 1000


def is_main_hd_frame(width: int, height: int) -> bool:
    return int(width) >= MAIN_HD_MIN_WIDTH and int(height) >= MAIN_HD_MIN_HEIGHT


def evidence_dir(event_id: str) -> Path:
    eid = event_id.strip()
    return get_settings().data_path / _EVIDENCE_SUBDIR / eid


def snapshot_file(event_id: str) -> Path:
    return evidence_dir(event_id) / "snapshot.jpg"


def evidence_video_file(event_id: str) -> Path:
    return evidence_dir(event_id) / "evidence.mp4"


def _data_url(relpath: str, *, version: str | None = None) -> str:
    rel = relpath.strip().lstrip("/")
    v = (version or "").strip()
    if v:
        return f"/data/{rel}?v={quote(v, safe='')}"
    return f"/data/{rel}"


def snapshot_data_url(event_id: str) -> str:
    eid = event_id.strip()
    return _data_url(f"{_EVIDENCE_SUBDIR}/{eid}/snapshot.jpg", version=str(int(time.time())))


def evidence_video_data_url(event_id: str) -> str:
    eid = event_id.strip()
    return _data_url(f"{_EVIDENCE_SUBDIR}/{eid}/evidence.mp4", version=str(int(time.time())))


def remove_evidence_files(event_id: str) -> None:
    root = evidence_dir(event_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def _extract_video_frame_jpeg(video_path: str, time_sec: float, out_path: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{max(0.0, time_sec):.3f}",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                out_path,
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _jpeg_dimensions(path: Path) -> tuple[int, int]:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0 and "x" in out.stdout:
            w, h = out.stdout.strip().split("x", 1)
            return max(1, int(w)), max(1, int(h))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return 1280, 720


def _rescale_boxes_inplace(
    payload: dict[str, Any],
    old_w: int,
    old_h: int,
    new_w: int,
    new_h: int,
) -> None:
    boxes = payload.get("boxes")
    if not isinstance(boxes, list) or old_w <= 0 or old_h <= 0:
        return
    sx = new_w / old_w
    sy = new_h / old_h
    if abs(sx - 1.0) < 0.001 and abs(sy - 1.0) < 0.001:
        return
    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            box["x"] = round(float(box["x"]) * sx, 2)
            box["y"] = round(float(box["y"]) * sy, 2)
            box["width"] = round(float(box["width"]) * sx, 2)
            box["height"] = round(float(box["height"]) * sy, 2)
        except (TypeError, ValueError, KeyError):
            continue


def _normalize_boxes(payload: dict[str, Any], width: int, height: int) -> None:
    boxes = payload.get("boxes")
    if not isinstance(boxes, list):
        return
    w = max(1, int(width))
    h = max(1, int(height))
    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            x = float(box.get("x", 0))
            y = float(box.get("y", 0))
            bw = float(box.get("width", 0))
            bh = float(box.get("height", 0))
        except (TypeError, ValueError):
            continue
        if max(x, y, x + bw, y + bh) <= 1.5:
            box["x"] = round(x * w, 2)
            box["y"] = round(y * h, 2)
            box["width"] = round(bw * w, 2)
            box["height"] = round(bh * h, 2)


_MAX_VIDEO_FRAME_MS = 3_600_000
_MAX_VIDEO_TIME_SEC = 3600.0


def sanitize_detection_timing(payload: dict[str, Any]) -> None:
    """清除 VAIO 绝对时间戳误当作视频偏移的 frame_ms / video_time_sec。"""
    frame_ms = payload.get("frame_ms")
    try:
        fm = int(frame_ms) if frame_ms is not None else 0
    except (TypeError, ValueError):
        fm = 0
    if fm <= 0 or fm > _MAX_VIDEO_FRAME_MS:
        payload.pop("frame_ms", None)
    vts = payload.get("video_time_sec")
    try:
        v = float(vts) if vts is not None else -1.0
    except (TypeError, ValueError):
        v = -1.0
    if v < 0 or v > _MAX_VIDEO_TIME_SEC:
        payload.pop("video_time_sec", None)


def _maybe_repair_snapshot_jpeg(path: Path) -> None:
    """将磁盘上 ffmpeg Lavc 注释头 JPEG 转为浏览器可显示的 JFIF。"""
    if not path.is_file():
        return
    try:
        head = path.read_bytes()[:4]
    except OSError:
        return
    if len(head) < 4 or head[:2] != b"\xff\xd8" or head[2:4] != b"\xff\xfe":
        return
    try:
        raw = path.read_bytes()
    except OSError:
        return
    _write_jpeg_file(path, raw)


def align_detection_payload_to_snapshot(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """将 detection_json 坐标系与取证抓拍 JPEG 尺寸对齐。"""
    if not isinstance(payload, dict):
        return payload
    snap_path = snapshot_file(event_id)
    _maybe_repair_snapshot_jpeg(snap_path)
    if not snap_path.is_file():
        sanitize_detection_timing(payload)
        return payload
    new_w, new_h = _jpeg_dimensions(snap_path)
    old_w = int(payload.get("source_width") or 0)
    old_h = int(payload.get("source_height") or 0)
    if old_w > 0 and old_h > 0:
        _rescale_boxes_inplace(payload, old_w, old_h, new_w, new_h)
    payload["source_width"] = new_w
    payload["source_height"] = new_h
    _normalize_boxes(payload, new_w, new_h)
    sanitize_detection_timing(payload)
    return payload


def _write_jpeg_file(dest: Path, data: bytes) -> bool:
    from inspection_platform.equipment.jpeg_norm import normalize_jpeg_bytes

    normalized = normalize_jpeg_bytes(data)
    if not normalized:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(normalized)
    return True


def _capture_snapshot(
    dest: Path,
    rtsp_url: str,
    *,
    equipment_id: str = "",
) -> bool:
    """优先经 go2rtc 抓帧；go2rtc 不可用时才直连摄像机 RTSP。"""
    url = (rtsp_url or "").strip()
    eq = (equipment_id or "").strip()
    if eq and url:
        try:
            from inspection_platform.media.service import get_media_service

            data = get_media_service().grab_frame_jpeg(eq, url, stream_mode="main", quality="hd")
            if data and _write_jpeg_file(dest, data):
                w, h = _jpeg_dimensions(dest)
                if is_main_hd_frame(w, h):
                    return True
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("go2rtc 取证抓拍失败 equipment=%s: %s", eq, exc)
    if not url:
        return False
    try:
        from inspection_platform.equipment.rtsp_live import grab_rtsp_snapshot

        data = grab_rtsp_snapshot(url, timeout_sec=20, stream="main")
    except Exception as exc:
        logger.warning("RTSP 取证抓拍失败 url=%s error=%s", url, exc)
        return False
    if not _write_jpeg_file(dest, data):
        return False
    w, h = _jpeg_dimensions(dest)
    if not is_main_hd_frame(w, h):
        logger.warning(
            "取证抓拍非1080p主码流，已丢弃 size=%dx%d path=%s",
            w,
            h,
            dest,
        )
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def attach_rtsp_snapshot_to_event(
    event_id: str,
    detection_json: str,
    rtsp_url: str,
    *,
    equipment_id: str = "",
    force_refresh: bool = False,
) -> str:
    """为视频事件保存 RTSP 单帧，并写入 detection_json。"""
    eid = event_id.strip()
    url = (rtsp_url or "").strip()
    eq = (equipment_id or "").strip()
    if not eid or not url:
        return detection_json

    snap_path = snapshot_file(eid)
    if snap_path.is_file() and snap_path.stat().st_size > 256 and not force_refresh:
        payload: dict[str, Any] = {}
        if (detection_json or "").strip():
            try:
                parsed = json.loads(detection_json)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = {}
        if not str(payload.get("snapshot_url") or "").strip():
            w, h = _jpeg_dimensions(snap_path)
            payload["snapshot_url"] = snapshot_data_url(eid)
            payload.setdefault("source_width", w)
            payload.setdefault("source_height", h)
            payload = align_detection_payload_to_snapshot(eid, payload)
            return json.dumps(payload, ensure_ascii=False)
        return detection_json

    snap_path.parent.mkdir(parents=True, exist_ok=True)
    if not _capture_snapshot(snap_path, url, equipment_id=eq):
        return detection_json

    w, h = _jpeg_dimensions(snap_path)
    payload: dict[str, Any] = {}
    if (detection_json or "").strip():
        try:
            parsed = json.loads(detection_json)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    payload["snapshot_url"] = snapshot_data_url(eid)
    payload["source_width"] = w
    payload["source_height"] = h
    payload = align_detection_payload_to_snapshot(eid, payload)
    return json.dumps(payload, ensure_ascii=False)


def attach_alert_frame_evidence(
    event_id: str,
    jpeg_bytes: bytes,
    detection_json: str,
    *,
    video_time_sec: float | None = None,
) -> str:
    """
    告警同帧取证：将告警瞬间抓到的 JPEG 写入取证目录，并把已有 bbox 缩放到抓拍坐标系。
    """
    eid = event_id.strip()
    data = jpeg_bytes if isinstance(jpeg_bytes, bytes) else b""
    if not eid or len(data) < 256:
        return detection_json

    snap_path = snapshot_file(eid)
    if not _write_jpeg_file(snap_path, data):
        return detection_json

    payload: dict[str, Any] = {}
    if (detection_json or "").strip():
        try:
            parsed = json.loads(detection_json)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    w, h = _jpeg_dimensions(snap_path)
    old_w = int(payload.get("source_width") or 0)
    old_h = int(payload.get("source_height") or 0)
    if old_w > 0 and old_h > 0:
        _rescale_boxes_inplace(payload, old_w, old_h, w, h)
    payload["source_width"] = w
    payload["source_height"] = h
    payload["snapshot_url"] = snapshot_data_url(eid)
    # 抓拍为告警后 go2rtc 单帧，未必与 VAIO 检测帧同画面；由 refill/snapshot LLM 校验后再标记对齐
    payload.pop("snapshot_aligned", None)
    payload.pop("snapshot_mismatch", None)
    payload.pop("judgment_note", None)
    payload.pop("judgment_source", None)
    if video_time_sec is not None and video_time_sec >= 0:
        payload["video_time_sec"] = round(float(video_time_sec), 3)
    _normalize_boxes(payload, w, h)
    boxes = payload.get("boxes")
    if isinstance(boxes, list):
        confs: list[float] = []
        for box in boxes:
            if not isinstance(box, dict):
                continue
            try:
                c = float(box.get("confidence") or 0)
                if c > 0:
                    confs.append(c)
            except (TypeError, ValueError):
                continue
        if confs:
            payload["display_confidence"] = max(confs)
    payload = align_detection_payload_to_snapshot(eid, payload)
    return json.dumps(payload, ensure_ascii=False)


def _is_local_media_file(path: str) -> bool:
    return bool(path) and os.path.isfile(path)


def _is_stream_media_url(path: str) -> bool:
    low = (path or "").strip().lower()
    return low.startswith(("rtsp://", "rtmp://", "http://", "https://"))


def repair_snapshot_from_rtsp(
    event_id: str,
    equipment_id: str,
    detection_json: str,
    *,
    force_refresh: bool = True,
) -> str:
    """用设备 RTSP 实时流刷新事件取证抓拍。"""
    eid = event_id.strip()
    eq = (equipment_id or "").strip()
    if not eid or not eq:
        return detection_json
    try:
        from inspection_platform.equipment.service import EquipmentService
        from inspection_platform.equipment.stream_url import normalize_stream_url

        row = EquipmentService().get(eq)
        if not row:
            return detection_json
        rtsp = normalize_stream_url(str(row.get("platform_address") or ""))
        if not rtsp:
            return detection_json
        return attach_rtsp_snapshot_to_event(
            eid,
            detection_json,
            rtsp,
            equipment_id=eq,
            force_refresh=force_refresh and not snapshot_file(eid).is_file(),
        )
    except Exception as exc:
        logger.warning("RTSP 取证修复失败 event_id=%s equipment=%s error=%s", eid, eq, exc)
        return detection_json


def attach_detection_evidence(
    event_id: str,
    detection_json: str,
    ctx: dict[str, Any],
) -> str:
    """
  将检测帧 JPEG 与（可选）分析用视频片段写入 data/，并更新 detection_json 中的媒体 URL 与坐标系。

  ctx 字段：
    - equipment_id: 设备 id（用于 RTSP 取证）
    - analysis_video_path: VAIO/LLM 分析所用路径（RTSP 或临时片段）
    - original_video_path: 截取片段前的完整视频（可选，已停用本地文件源）
    - window_start_sec: 持续监控窗口在原片上的起点（秒）
    - is_analysis_clip: 分析路径是否为临时片段
    - src_data_type: 1=直播流（平台仅支持 RTSP 直播）
    - rtsp_url: 直播 RTSP 地址（src_data_type=1 时）
  """
    raw = (detection_json or "").strip()
    if not raw:
        return detection_json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return detection_json
    if not isinstance(payload, dict):
        return detection_json

    analysis_path = str(ctx.get("analysis_video_path") or "").strip()
    original_path = str(ctx.get("original_video_path") or "").strip()
    window_start = float(ctx.get("window_start_sec") or 0.0)
    is_clip = bool(ctx.get("is_analysis_clip"))
    src_data_type = int(ctx.get("src_data_type") or 2)
    rtsp_url = str(ctx.get("rtsp_url") or "").strip()
    equipment_id = str(ctx.get("equipment_id") or "").strip()

    video_time_raw = payload.get("video_time_sec")
    try:
        frame_time = float(video_time_raw) if video_time_raw is not None else 0.0
    except (TypeError, ValueError):
        frame_time = 0.0
    frame_time = max(0.0, frame_time)

    eid = event_id.strip()
    snap_path = snapshot_file(eid)
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    snap_ok = False
    if equipment_id and rtsp_url:
        snap_ok = _capture_snapshot(snap_path, rtsp_url, equipment_id=equipment_id)
    if not snap_ok and src_data_type == 1 and rtsp_url:
        snap_ok = _capture_snapshot(snap_path, rtsp_url, equipment_id=equipment_id)
    if not snap_ok and analysis_path and _is_stream_media_url(analysis_path):
        snap_ok = _extract_video_frame_jpeg(analysis_path, frame_time, str(snap_path))

    if snap_ok and snap_path.is_file():
        w, h = _jpeg_dimensions(snap_path)
        old_w = int(payload.get("source_width") or 0)
        old_h = int(payload.get("source_height") or 0)
        if old_w > 0 and old_h > 0:
            _rescale_boxes_inplace(payload, old_w, old_h, w, h)
        payload["source_width"] = w
        payload["source_height"] = h
        payload["snapshot_url"] = snapshot_data_url(eid)
        _normalize_boxes(payload, w, h)
    else:
        logger.warning(
            "事件取证抓拍失败 event_id=%s analysis=%s clip=%s rtsp=%s",
            eid,
            analysis_path or original_path,
            is_clip,
            bool(rtsp_url),
        )

    if is_clip and analysis_path and os.path.isfile(analysis_path):
        try:
            os.unlink(analysis_path)
        except OSError:
            pass
    elif window_start > 0 and not is_clip and original_path and os.path.isfile(original_path):
        payload["video_offset_sec"] = round(window_start, 3)

    if snap_path.is_file():
        payload = align_detection_payload_to_snapshot(eid, payload)

    return json.dumps(payload, ensure_ascii=False)

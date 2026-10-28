"""手动触发巡检业务：调用算法并将结果写入巡检事件表。"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inspection_platform.algorithm.service import AlgorithmService
from inspection_platform.document.region_meta import RegionMetaService
from inspection_platform.equipment.service import EquipmentService
from inspection_platform.equipment.stream_url import normalize_stream_url
from inspection_platform.inspection_event.service import InspectionEventService

logger = logging.getLogger(__name__)

# 持续监控：内置每 10 秒 tick，分析前 10 秒画面（与前端展示一致）
CONTINUOUS_CHECK_INTERVAL_SEC = 10
CONTINUOUS_ANALYSIS_WINDOW_SEC = 10
CONTINUOUS_SCHEDULE_INTERVAL_LABEL = "每10秒"


def _continuous_window_on_file(duration_sec: float, window_sec: float) -> tuple[float, float]:
    """模拟实时流：按墙钟对齐录像时间轴，取「前 window_sec 秒」窗口。"""
    dur = max(0.5, float(duration_sec))
    win = max(0.5, float(window_sec))
    end_sec = time.time() % dur
    start_sec = max(0.0, end_sec - win)
    seg_dur = max(0.5, end_sec - start_sec)
    return start_sec, seg_dur


def _grab_rtsp_jpeg_via_ffmpeg(rtsp_url: str, out_path: str, *, timeout: float = 25.0) -> bool:
    """go2rtc 不可用时直连主码流 RTSP 抽一帧（禁止子码流 /102）。"""
    url = _main_stream_rtsp_url(rtsp_url)
    if not url:
        return False
    if "#" not in url:
        url = f"{url}#rtsp_transport=tcp"
    cmd = [
        "ffmpeg",
        "-y",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        out_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 512


# 大模型检测 / 告警取证：仅接受主码流 1080p（拒绝 720p 子码流帧）
from inspection_platform.inspection_event.evidence import is_main_hd_frame


def _main_stream_rtsp_url(rtsp_url: str) -> str:
    from inspection_platform.equipment.rtsp_live import pick_stream_url

    return pick_stream_url((rtsp_url or "").strip(), stream="main")


def _jpeg_dimensions_from_bytes(data: bytes) -> tuple[int, int]:
    from inspection_platform.inspection_event.evidence import _jpeg_dimensions

    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="iw-dim-probe-")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return _jpeg_dimensions(Path(path))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _grab_main_hd_jpeg(equipment_id: str, camera_rtsp: str) -> tuple[bytes, int, int] | None:
    """仅主码流 1080p 抓帧（go2rtc main → ffmpeg 主码流），跳过低分辨率帧。"""
    eq = (equipment_id or "").strip()
    main_url = _main_stream_rtsp_url(camera_rtsp)
    if not eq or not main_url:
        return None

    candidates: list[bytes] = []

    try:
        from inspection_platform.media.service import get_media_service

        media = get_media_service()
        for attempt in range(3):
            jpeg = media.grab_frame_jpeg(eq, main_url, stream_mode="main", quality="hd")
            if jpeg:
                candidates.append(jpeg)
            if attempt < 2:
                time.sleep(0.4)
    except Exception as exc:
        logger.warning("主码流 go2rtc 抓帧失败 equipment=%s: %s", eq, exc)

    fd, temp_jpg = tempfile.mkstemp(suffix=".jpg", prefix="iw-main-hd-")
    os.close(fd)
    try:
        if _grab_rtsp_jpeg_via_ffmpeg(main_url, temp_jpg):
            candidates.append(Path(temp_jpg).read_bytes())
    finally:
        try:
            os.unlink(temp_jpg)
        except OSError:
            pass

    for jpeg in candidates:
        w, h = _jpeg_dimensions_from_bytes(jpeg)
        if is_main_hd_frame(w, h):
            logger.info("大模型检测主码流抓帧 equipment=%s %dx%d bytes=%d", eq, w, h, len(jpeg))
            return jpeg, w, h
        logger.warning(
            "跳过非1080p帧 equipment=%s size=%dx%d（仅使用主码流1080p）",
            eq,
            w,
            h,
        )
    return None


def _extract_video_clip(video_path: str, *, start_sec: float, duration_sec: float) -> str:
    """截取本地 mp4 片段供持续监控单 tick 分析。"""
    fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="iw-continuous-")
    os.close(fd)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, start_sec):.3f}",
        "-i",
        video_path,
        "-t",
        f"{max(0.5, duration_sec):.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-an",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    if proc.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 1024:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg 截取监控窗口失败: {proc.stderr.decode(errors='ignore')[:200]}")
    return out_path


def _utc_now() -> str:
    from inspection_platform.timeutil import utc_now_iso

    return utc_now_iso()


def _vaio_config_log_summary(config: dict[str, Any]) -> dict[str, Any]:
    """日志用：省略 defence 点坐标细节，仅保留区域数量。"""
    summary: dict[str, Any] = {}
    for key, val in config.items():
        if key == "defence":
            if isinstance(val, list):
                summary["defence_zones"] = len(val)
            continue
        summary[key] = val
    return summary


def _detecttype_from_algo_name(name: str) -> int | None:
    """按算法显示名称推断 VAIO detecttype（与 vaio-analysis-core 配方一致）。"""
    n = name.strip()
    if not n:
        return None
    if "人员密集" in n and ("跌倒" in n or "摔倒" in n):
        return 1016
    if "焊接" in n and ("跌倒" in n or "摔倒" in n):
        return 1005
    if "卧倒" in n or "摔倒" in n or "跌倒" in n:
        return 1018
    if "大模型" in n and "打电话" in n:
        return None  # 走 llm_detect 直连，非 VAIO detecttype
    if "大模型" in n and ("玩手机" in n or "手机" in n):
        return None
    if "手机" in n or "玩手机" in n:
        return 1004
    if "火光" in n or "动火" in n or "明火" in n:
        return 1017
    return None


_LLM_DETECTTYPES = frozenset(
    {
        1000,
        1001,
        1004,
        1005,
        1006,
        1007,
        1008,
        1009,
        1010,
        1011,
        1015,
        1016,
        1017,
        1018,
    }
)

# VAIO 姿态摔倒链路（poserecog）易误报，需 LLM 单帧复核后才入库。
_POSE_FALL_DETECTTYPES = frozenset({1005, 1016, 1018})

# LLM 链路 bbox 多沿用上游 YOLO person 框，UI 需展示算法语义而非 class_name。
_DETECTTYPE_BOX_LABEL: dict[int, str] = {
    1004: "玩手机",
    1005: "摔倒",
    1016: "摔倒",
    1018: "摔倒",
    1017: "明火",
}
_GENERIC_BOX_CLASS_NAMES = frozenset({"person", "people", "human", ""})

_VAIO_LIVE_REF_WIDTH = 1920
_VAIO_LIVE_REF_HEIGHT = 1080


def _grab_alert_snapshot(equipment_id: str, camera_rtsp: str) -> bytes | None:
    """告警瞬间经 go2rtc 主码流 1080p 抓帧。"""
    packed = _grab_main_hd_jpeg(equipment_id, camera_rtsp)
    return packed[0] if packed else None


def _capture_alert_snapshot_into_ctx(ctx: dict[str, Any], equipment_id: str) -> None:
    if ctx.get("alert_snapshot_bytes"):
        return
    if int(ctx.get("src_data_type") or 0) != 1:
        return
    rtsp = str(ctx.get("rtsp_url") or "").strip()
    if not rtsp:
        return
    data = _grab_alert_snapshot(equipment_id, rtsp)
    if data:
        ctx["alert_snapshot_bytes"] = data
        logger.info("告警同帧抓拍 equipment=%s bytes=%d", equipment_id, len(data))


def _ensure_vaio_upload_config(config: dict[str, Any]) -> dict[str, Any]:
    """holddowntime 与 upload.suppressEnabled 需成对出现，否则 C++ 核心创建任务失败。"""
    out = dict(config)
    if out.get("holddowntime") is not None and "suppressEnabled" not in out:
        out["suppressEnabled"] = 1
    return out


def _vaio_poll_seconds(
    params: dict[str, Any],
    detecttype: int,
    *,
    video_duration_sec: float | None = None,
) -> int:
    frame_interval = max(1, int(float(params.get("frame_interval", 5))))
    base = min(120, max(15, frame_interval * 6))
    if detecttype in _LLM_DETECTTYPES:
        base = max(base, 90)
        if video_duration_sec and video_duration_sec > 0:
            base = max(base, int(video_duration_sec) + 60)
    return base


_LLM_RULE_API = os.environ.get(
    "SIA_LLM_RULE_API", "http://10.19.155.38:8848/api/process-rule"
).strip()

_PHONE_LLM_PROMPT = (
    "仅检测正在用手机打电话的人员；必须看清手机机身且贴耳通话。"
    "手背/背对镜头、托腮揉眼、扶头、键盘办公、看不清手机一律阴性，不得出框。"
)

_FALL_LLM_PROMPT = (
    "仅当画面中能清晰辨认完整人体（必须可见头部与躯干轮廓）且处于意外跌倒、失去平衡倒地状态时判定为阳性。"
    "正常站立、行走、弯腰、蹲姿、跪姿作业一律为阴性；阴性时不得输出检测框。"
    "地毯纹理、坐垫、阴影、反光、空地面等非人体区域一律为阴性。"
)

# 大模型判定说明中的否定/非摔倒语境（含这些词则视为阴性，即使 confidence 偏高）
_FALL_LLM_NEG_MARKERS = (
    "不符合阳性",
    "判定为阴性",
    "阴性",
    "未呈现",
    "不属于",
    "排除",
    "正常弯腰",
    "正常蹲",
    "正常站立",
    "正常行走",
    "跪姿",
    "跪着",
    "跪地",
    "跪趴",
    "作业",
    "检修",
    "捡",
)


def _is_fall_llm_positive(desc: str) -> bool:
    """解析摔倒 LLM 判定说明：排除否定句中的「跌倒/卧倒」字样误匹配。"""
    text = desc.strip()
    if not text:
        return False
    if any(m in text for m in _FALL_LLM_NEG_MARKERS):
        return False
    if not any(k in text for k in ("摔倒", "跌倒", "失去平衡", "意外倒地", "倒地")):
        return False
    return any(k in text for k in ("人体", "头部", "躯干", "人员", "行人"))

_LLM_PROMPT_BY_DETECTTYPE: dict[int, str] = {
    1004: _PHONE_LLM_PROMPT,
    1005: _FALL_LLM_PROMPT,
    1016: _FALL_LLM_PROMPT,
    1018: _FALL_LLM_PROMPT,
}


def _llm_rule_prompt(detecttype: int | None) -> str:
    if detecttype is not None and detecttype in _LLM_PROMPT_BY_DETECTTYPE:
        return _LLM_PROMPT_BY_DETECTTYPE[detecttype]
    return _PHONE_LLM_PROMPT


def _llm_confidence_threshold(params: dict[str, Any]) -> float:
    for key in ("detection/person/threshold", "confidence"):
        raw = params.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
            return val if 0 < val <= 1 else val / 100.0 if val > 1 else 0.5
        except (TypeError, ValueError):
            continue
    return 0.5


def _is_valid_llm_hit(hit: dict[str, Any], detecttype: int | None) -> bool:
    """过滤 VAIO 日志中空 description 或片头误报（如 11.5s 抱手被标 95%）。"""
    desc = str(hit.get("description") or "").strip()
    if detecttype == 1004:
        if "手机" in desc or "玩手机" in desc:
            return True
        try:
            conf = float(hit.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf > 0 and hit.get("bbox") is not None:
            return True
        return False
    if not desc:
        return False
    if detecttype in _POSE_FALL_DETECTTYPES:
        return _is_fall_llm_positive(desc)
    return True


def _llm_hit_box_label(hit: dict[str, Any], detecttype: int | None = None) -> str:
    """检测框展示标签：玩手机等 LLM 算法 bbox 来自 person 检测，class_name 不能直出 UI。"""
    class_name = str(hit.get("class_name") or "").strip()
    desc = str(hit.get("description") or "").strip()
    generic = class_name.lower() in _GENERIC_BOX_CLASS_NAMES

    if detecttype == 1004:
        if "玩手机" in desc or "手机" in desc:
            return "玩手机"
        return _DETECTTYPE_BOX_LABEL[1004]

    llm_kind = str(hit.get("llm_kind") or "").strip()
    if llm_kind == "phone_call":
        return "打电话"
    if llm_kind == "play_phone":
        return "玩手机"

    if detecttype in _POSE_FALL_DETECTTYPES:
        if _is_fall_llm_positive(desc):
            return _DETECTTYPE_BOX_LABEL.get(detecttype, "摔倒")
        if generic:
            return _DETECTTYPE_BOX_LABEL.get(detecttype, "摔倒")
        return class_name

    algo_label = _DETECTTYPE_BOX_LABEL.get(detecttype) if detecttype is not None else None
    if algo_label and generic:
        return algo_label
    if desc and generic and len(desc) <= 40:
        return desc
    return class_name


def _normalize_detection_box_labels(
    payload: dict[str, Any],
    detecttype: int | None,
    *,
    description: str | None = None,
) -> dict[str, Any]:
    """已有事件中 person 标签按算法类型覆写，避免详情页仍显示 YOLO 类别名。"""
    if detecttype is None or not isinstance(payload.get("boxes"), list):
        return payload
    desc = str(
        description
        or payload.get("llm_description")
        or payload.get("resolution_detail")
        or ""
    ).strip()
    out = dict(payload)
    boxes: list[dict[str, Any]] = []
    for box in out["boxes"]:
        if not isinstance(box, dict):
            boxes.append(box)
            continue
        item = dict(box)
        label = str(item.get("label") or "").strip()
        if label.lower() in _GENERIC_BOX_CLASS_NAMES:
            item["label"] = _llm_hit_box_label(
                {"class_name": label, "description": desc},
                detecttype,
            )
        boxes.append(item)
    out["boxes"] = boxes
    return out


def _enrich_llm_hit_times(
    hits: list[dict[str, Any]], *, video_duration_sec: float | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        item = dict(hit)
        if video_duration_sec and item.get("frame_ms") is not None:
            vts = _video_time_from_frame_ms(item.get("frame_ms"), video_duration_sec)
            if vts is not None:
                item["video_time_sec"] = round(vts, 3)
        out.append(item)
    return out


def _call_llm_process_rule(
    *,
    image_path: str,
    image_name_ms: int,
    detecttype: int | None,
    threshold: float,
) -> list[dict[str, Any]]:
    api = _LLM_RULE_API
    if not api:
        return []
    try:
        raw = Path(image_path).read_bytes()
    except OSError as exc:
        logger.debug("读取补扫帧失败 path=%s error=%s", image_path, exc)
        return []
    import base64

    b64 = base64.b64encode(raw).decode()
    payload = {
        "rule": [
            {
                "id": 0,
                "prompt": _llm_rule_prompt(detecttype),
                "threshold": threshold,
            }
        ],
        "images": [
            {
                "image_name": str(image_name_ms),
                "url": f"data:image/jpeg;base64,{b64}",
            }
        ],
    }
    req = urllib.request.Request(
        api,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("LLM 补扫请求失败 api=%s error=%s", api, exc)
        return []

    hits: list[dict[str, Any]] = []
    for img in body.get("processedImages") or []:
        if not isinstance(img, dict) or not img.get("success"):
            continue
        for det in img.get("detections") or []:
            if not isinstance(det, dict):
                continue
            try:
                conf = float(det.get("confidence") or 0)
            except (TypeError, ValueError):
                continue
            if conf < threshold:
                continue
            hits.append(
                {
                    "confidence": conf,
                    "class_name": str(det.get("class_name") or "").strip(),
                    "description": str(det.get("description") or "").strip(),
                    "bbox": det.get("bbox"),
                    "frame_ms": image_name_ms,
                    "video_time_sec": round(image_name_ms / 1000.0, 3),
                    "source": "ffmpeg_llm_rescan",
                }
            )
    return hits


def _scan_local_video_llm_hits(
    *,
    video_path: str,
    frame_interval_sec: float,
    detecttype: int | None,
    threshold: float,
    video_duration_sec: float,
) -> list[dict[str, Any]]:
    """本地 mp4 按抽帧间隔补扫，避免 VAIO 跳帧/循环导致 18–19s 漏检或 11s 误报。"""
    interval = max(1.0, float(frame_interval_sec))
    duration = max(0.5, float(video_duration_sec))
    hits: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="iw-llm-scan-") as tmp:
        t = 0.0
        while t < duration - 0.05:
            frame_ms = int(round(t * 1000))
            out_path = os.path.join(tmp, f"f_{frame_ms}.jpg")
            try:
                proc = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        f"{t:.3f}",
                        "-i",
                        video_path,
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        out_path,
                    ],
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                t += interval
                continue
            if proc.returncode != 0 or not os.path.isfile(out_path):
                t += interval
                continue
            hits.extend(
                _call_llm_process_rule(
                    image_path=out_path,
                    image_name_ms=frame_ms,
                    detecttype=detecttype,
                    threshold=threshold,
                )
            )
            t += interval
    valid = [h for h in hits if _is_valid_llm_hit(h, detecttype)]
    logger.info(
        "LLM 本地补扫完成 path=%s frames=%d raw_hits=%d valid_hits=%d interval=%ss",
        video_path,
        int(duration / interval) + 1,
        len(hits),
        len(valid),
        interval,
    )
    return valid


def _resolve_llm_hit_for_video(
    *,
    task_id: str,
    detecttype: int,
    params: dict[str, Any],
    video_url: str,
    src_data_type: int,
    video_duration_sec: float | None,
) -> dict[str, Any] | None:
    vaio_hits = _enrich_llm_hit_times(
        _parse_llm_hits_from_vaio_logs(task_id),
        video_duration_sec=video_duration_sec,
    )
    valid_vaio = [h for h in vaio_hits if _is_valid_llm_hit(h, detecttype)]
    scan_hits: list[dict[str, Any]] = []
    if (
        src_data_type == 2
        and video_duration_sec
        and os.path.isfile(video_url)
        and detecttype in _LLM_DETECTTYPES
    ):
        frame_interval = max(1, int(float(params.get("frame_interval", 5))))
        scan_hits = _scan_local_video_llm_hits(
            video_path=video_url,
            frame_interval_sec=float(frame_interval),
            detecttype=detecttype,
            threshold=_llm_confidence_threshold(params),
            video_duration_sec=video_duration_sec,
        )
    pool = valid_vaio + scan_hits
    if not pool:
        return None
    picked = _best_llm_hit(pool, video_duration_sec=video_duration_sec)
    if picked:
        src = picked.get("source", "vaio_log")
        vts = picked.get("video_time_sec")
        logger.info(
            "LLM 命中选取 task_id=%s source=%s video_time_sec=%s confidence=%.3f vaio_valid=%d scan=%d",
            task_id,
            src,
            vts,
            float(picked.get("confidence") or 0),
            len(valid_vaio),
            len(scan_hits),
        )
    return picked


def _extract_video_frame_jpeg(video_path: str, time_sec: float, out_path: str) -> bool:
    """从本地 mp4 截取指定时刻的单帧 JPEG。"""
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
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and os.path.isfile(out_path)


def _verify_vaio_pose_event_with_llm(
    *,
    video_path: str,
    detecttype: int,
    params: dict[str, Any],
    video_time_sec: float,
) -> dict[str, Any] | None:
    """对 VAIO 姿态摔倒告警做单帧 LLM 复核，过滤地面物体等误报。"""
    frame_ms = int(round(max(0.0, video_time_sec) * 1000))
    out_path = os.path.join(
        tempfile.gettempdir(),
        f"iw-fall-verify-{frame_ms}-{int(time.time() * 1000)}.jpg",
    )
    try:
        if not _extract_video_frame_jpeg(video_path, video_time_sec, out_path):
            return None
        hits = _call_llm_process_rule(
            image_path=out_path,
            image_name_ms=frame_ms,
            detecttype=detecttype,
            threshold=_llm_confidence_threshold(params),
        )
        for hit in hits:
            hit["frame_ms"] = frame_ms
            hit["video_time_sec"] = round(video_time_sec, 3)
            hit["source"] = "llm_pose_verify"
        valid = [h for h in hits if _is_valid_llm_hit(h, detecttype)]
        return valid[0] if valid else None
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _probe_video_duration_sec(video_path: str) -> float | None:
    """本地 mp4 时长（秒），用于 LLM 抽帧/选帧对齐。"""
    path = (video_path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0:
            return None
        val = float(out.stdout.strip())
        return val if val > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _probe_video_dimensions(video_path: str) -> tuple[int, int]:
    """本地 mp4 宽高（像素），用于检测框坐标与前端 overlay 对齐。"""
    path = (video_path or "").strip()
    if not path or not os.path.isfile(path):
        return 1280, 720
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
                path,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0:
            return 1280, 720
        parts = out.stdout.strip().split("x")
        if len(parts) != 2:
            return 1280, 720
        w, h = int(parts[0]), int(parts[1])
        return (w, h) if w > 0 and h > 0 else (1280, 720)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 1280, 720


def _frame_interval_to_vaio_fps(frame_interval: Any) -> float:
    """与前端 equipmentAlgoConfig.frameIntervalToVaioFps 一致：每 N 秒 1 帧 → fps。"""
    try:
        interval = max(1.0, float(frame_interval))
    except (TypeError, ValueError):
        interval = 5.0
    return round(1.0 / interval, 4)


def _video_time_from_frame_ms(frame_ms: int | None, duration_sec: float | None) -> float | None:
    if frame_ms is None or frame_ms <= 0 or not duration_sec or duration_sec <= 0:
        return None
    duration_ms = max(1, int(round(duration_sec * 1000)))
    if frame_ms > duration_ms * 2 and frame_ms > 3_600_000:
        return None
    return (int(frame_ms) % duration_ms) / 1000.0


def _plausible_image_name_ms(frame_ms: Any) -> int:
    """VAIO image_name 为绝对时间戳时不得当作视频偏移传给 LLM。"""
    try:
        fm = int(frame_ms) if frame_ms is not None else 0
    except (TypeError, ValueError):
        return 0
    return fm if 0 < fm < 3_600_000 else 0


def _parse_vaio_detecttype(
    algorithm_id: str,
    algo_svc: AlgorithmService,
    *,
    algo_name: str = "",
) -> int | None:
    aid = algorithm_id.strip()
    if aid.startswith("vaio-"):
        try:
            return int(aid.split("-", 1)[1])
        except ValueError:
            return None

    row = algo_svc.get(aid)
    if row:
        link = str(row.get("link") or "")
        if link.startswith("vaio://algorithms/"):
            try:
                return int(link.rsplit("/", 1)[-1])
            except ValueError:
                pass
        schema = row.get("schema") if isinstance(row.get("schema"), dict) else {}
        vaio_id = schema.get("vaio_id")
        if vaio_id is not None:
            try:
                return int(vaio_id)
            except (TypeError, ValueError):
                pass
        name_hint = _detecttype_from_algo_name(str(row.get("name") or ""))
        if name_hint is not None:
            return name_hint

    return _detecttype_from_algo_name(algo_name)


def _build_vaio_config(params: dict[str, Any], *, detecttype: int | None = None) -> dict[str, Any]:
    raw = params.get("vaio_config")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return _ensure_vaio_upload_config(parsed)
        except json.JSONDecodeError:
            pass
    config: dict[str, Any] = {}
    for key in (
        "fps",
        "holddowntime",
        "sensitivity",
        "detection/person/threshold",
        "suppressEnabled",
    ):
        if key in params:
            config[key] = params[key]
    defence_raw = params.get("defence")
    if isinstance(defence_raw, str) and defence_raw.strip():
        try:
            defence = json.loads(defence_raw)
            if isinstance(defence, list):
                config["defence"] = defence
        except json.JSONDecodeError:
            pass
    config = _ensure_vaio_upload_config(config)
    # 抽帧间隔为设备算法 UI 可配置项，以 frame_interval 为准同步 VAIO fps
    if "frame_interval" in params:
        interval = params.get("frame_interval")
        config["fps"] = _frame_interval_to_vaio_fps(interval)
        logger.debug(
            "VAIO 抽帧 frame_interval=%s -> fps=%s",
            interval,
            config["fps"],
        )
    elif "fps" not in config:
        config["fps"] = _frame_interval_to_vaio_fps(params.get("frame_interval", 5))
    if detecttype in _POSE_FALL_DETECTTYPES:
        # 1018 配方默认 posetype 含站立/弯腰/蹲着等，易与真实摔倒混淆；运行期收窄为仅「摔倒=6」
        config["posetype"] = [6]
        config.setdefault("person/minlength", 80)
    return config


def _is_algo_enabled(params: dict[str, Any]) -> bool:
    return params.get("enabled") is not False


def _resolve_video_source(equip_svc: EquipmentService, equipment_id: str) -> tuple[str, int]:
    row = equip_svc.get(equipment_id)
    if row:
        addr = str(row.get("platform_address") or "").strip()
        stream = normalize_stream_url(addr)
        if stream:
            return stream, 1
    raise ValueError(
        f"设备 {equipment_id} 未配置可用 RTSP 地址（请在设备接入中填写 platform_address）"
    )


def _region_name_map(region_svc: RegionMetaService) -> dict[str, str]:
    try:
        rows = region_svc.list_regions()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict):
            rid = str(row.get("id") or "").strip()
            name = str(row.get("name") or rid).strip()
            if rid:
                out[rid] = name
    return out


def _event_gradient(kind: str) -> str:
    if kind == "sensor":
        return "linear-gradient(135deg, #ea580c22, #f9731644)"
    return "linear-gradient(135deg, #c0392b22, #e74c3c44)"


def _threshold_text(params: dict[str, Any], algo_id: str) -> str:
    if algo_id == "algo-4":
        val = params.get("threshold", 70)
        return f"阈值 {val} dB(A)"
    conf = params.get("confidence")
    if conf is not None:
        return f"置信度 ≥ {conf}"
    raw = params.get("detection/person/threshold")
    if raw is not None:
        return f"置信度 ≥ {raw}"
    return ""


def _vaio_events_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("events")
    if isinstance(events, list):
        return [e for e in events if isinstance(e, dict)]
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    return []


def _vaio_event_title(raw: dict[str, Any], algo_name: str) -> str:
    for key in ("title", "event_name", "name", "type", "label", "object_type"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            text = str(val).strip()
            if text.lower() not in ("event", "alarm"):
                return text if "告警" in text or "检测" in text else f"{text}告警"
    return f"{algo_name}检测告警"


def _vaio_event_confidence(raw: dict[str, Any]) -> float | None:
    for key in ("confidence", "score", "prob", "threshold"):
        val = raw.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def _vaio_x86_dir() -> Path:
    env = os.environ.get("VAIO_ANALYSIS_SERVICE_ROOT", "").strip()
    root = Path(env).resolve() if env else Path(__file__).resolve().parents[2] / "vaio-analysis-service"
    return root / "x86_64"


def _vaio_log_paths() -> list[Path]:
    x86 = _vaio_x86_dir()
    if not x86.is_dir():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    ordered: list[Path] = []
    for name in (f"log_{today}.log", "log.log"):
        p = x86 / name
        if p.is_file():
            ordered.append(p)
    ordered.extend(sorted(x86.glob("log_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5])
    seen: set[Path] = set()
    out: list[Path] = []
    for p in ordered:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def _parse_llm_hits_from_vaio_logs(task_id: str) -> list[dict[str, Any]]:
    """LLM 类算法在 VAIO 核心中常能检出，但 upload 组件未转为 /v1/events；从业务日志回补。"""
    tid = task_id.strip()
    if not tid:
        return []
    hits: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for log_path in _vaio_log_paths():
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug("读取 VAIO 日志失败 path=%s error=%s", log_path, exc)
            continue
        for line in text.splitlines():
            if tid not in line or "CComponentLLMEng::DetectImg" not in line:
                continue
            marker = "http response:"
            pos = line.find(marker)
            if pos < 0:
                continue
            payload = line[pos + len(marker) :].strip()
            if ", task id:" in payload:
                payload = payload.rsplit(", task id:", 1)[0].strip()
            if payload.endswith(","):
                payload = payload[:-1]
            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                continue
            images = body.get("processedImages")
            if not isinstance(images, list):
                continue
            for img in images:
                if not isinstance(img, dict):
                    continue
                detections = img.get("detections")
                if not isinstance(detections, list):
                    continue
                for det in detections:
                    if not isinstance(det, dict):
                        continue
                    try:
                        conf = float(det.get("confidence") or 0)
                    except (TypeError, ValueError):
                        continue
                    if conf <= 0:
                        continue
                    key = json.dumps(det, sort_keys=True, ensure_ascii=False)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    frame_ms: int | None = None
                    raw_name = img.get("image_name")
                    try:
                        if raw_name is not None and str(raw_name).strip().isdigit():
                            frame_ms = int(str(raw_name).strip())
                    except (TypeError, ValueError):
                        frame_ms = None
                    hits.append(
                        {
                            "confidence": conf,
                            "class_name": str(det.get("class_name") or "").strip(),
                            "description": str(det.get("description") or "").strip(),
                            "bbox": det.get("bbox"),
                            "frame_ms": frame_ms,
                        }
                    )
    return hits


def _best_llm_hit(
    hits: list[dict[str, Any]],
    *,
    video_duration_sec: float | None = None,
) -> dict[str, Any] | None:
    if not hits:
        return None

    def rank(h: dict[str, Any]) -> float:
        conf = float(h.get("confidence") or 0)
        vts = h.get("video_time_sec")
        if vts is None and video_duration_sec:
            vts = _video_time_from_frame_ms(h.get("frame_ms"), video_duration_sec)
        if vts is None:
            return conf
        # 演示/巡检录像中目标多出现在中后段；片头高置信度常为误报
        bonus = 0.0
        if video_duration_sec and video_duration_sec > 0:
            ratio = float(vts) / float(video_duration_sec)
            if ratio >= 0.75:
                bonus += 0.35
            elif ratio >= 0.65:
                bonus += 0.25
            elif ratio < 0.35:
                bonus -= 0.35
        if h.get("source") == "ffmpeg_llm_rescan":
            bonus += 0.05
        return conf + bonus

    return max(hits, key=rank)


def _alert_event_title(algo_name: str) -> str:
    name = (algo_name or "").strip()
    if not name:
        return "检测告警"
    if name.endswith("检测") or name.endswith("告警"):
        return f"{name}告警" if name.endswith("检测") else name
    return f"{name}检测告警"


def _box_from_xyxy(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    label: str = "",
    confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "x": min(x1, x2),
        "y": min(y1, y2),
        "width": abs(x2 - x1),
        "height": abs(y2 - y1),
        "label": label,
        "confidence": confidence,
    }


def _parse_bbox_to_xyxy(
    bbox: Any,
    *,
    source_width: int = 1280,
    source_height: int = 720,
) -> tuple[float, float, float, float] | None:
    """将 LLM/VAIO 多种 bbox 格式统一为像素 xyxy。"""
    w = max(1, int(source_width))
    h = max(1, int(source_height))
    try:
        if isinstance(bbox, dict):
            if "x1" in bbox or "x2" in bbox or "left" in bbox:
                x1 = float(bbox.get("x1", bbox.get("left", 0)))
                y1 = float(bbox.get("y1", bbox.get("top", 0)))
                x2 = float(bbox.get("x2", bbox.get("right", x1)))
                y2 = float(bbox.get("y2", bbox.get("bottom", y1)))
            else:
                x1 = float(bbox.get("x", 0))
                y1 = float(bbox.get("y", 0))
                bw = float(bbox.get("width", bbox.get("w", 0)))
                bh = float(bbox.get("height", bbox.get("h", 0)))
                x2, y2 = x1 + bw, y1 + bh
        elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x1, y1, a, b = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            if a > x1 and b > y1 and a <= w * 1.05 and b <= h * 1.05:
                x2, y2 = a, b
            else:
                x2, y2 = x1 + a, y1 + b
        else:
            return None
    except (TypeError, ValueError):
        return None
    if max(x1, y1, x2, y2) <= 1.5:
        x1 *= w
        y1 *= h
        x2 *= w
        y2 *= h
    if abs(x2 - x1) < 2 or abs(y2 - y1) < 2:
        return None
    x1 = max(0.0, min(x1, float(w)))
    y1 = max(0.0, min(y1, float(h)))
    x2 = max(0.0, min(x2, float(w)))
    y2 = max(0.0, min(y2, float(h)))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _merge_detection_payload(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in patch.items():
        if key == "boxes" and val:
            out["boxes"] = val
        elif val is not None and val != "":
            out[key] = val
    return out


def _apply_snapshot_llm_hit(
    payload: dict[str, Any],
    hit: dict[str, Any],
    *,
    event_id: str,
    source_width: int,
    source_height: int,
    detecttype: int | None = None,
) -> dict[str, Any]:
    """将抓拍 LLM 命中写入 detection_json，并标记与 JPEG 对齐。"""
    from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

    patch_json = _detection_json_from_llm_hit(
        hit,
        detecttype=detecttype,
        source_width=source_width,
        source_height=source_height,
    )
    if not patch_json:
        return payload
    patch = json.loads(patch_json)
    out = _merge_detection_payload(payload, patch)
    out["source_width"] = source_width
    out["source_height"] = source_height
    out["snapshot_aligned"] = True
    out.pop("snapshot_mismatch", None)
    out.pop("judgment_note", None)
    desc = str(hit.get("description") or "").strip()
    if desc:
        out["llm_description"] = desc
    try:
        conf_f = float(hit.get("confidence") or 0)
        if conf_f > 0:
            out["display_confidence"] = conf_f
    except (TypeError, ValueError):
        pass
    out["judgment_source"] = "snapshot_llm"
    return align_detection_payload_to_snapshot(event_id, out)


def _mark_snapshot_detection_mismatch(
    payload: dict[str, Any],
    *,
    event_id: str,
    source_width: int,
    source_height: int,
) -> dict[str, Any]:
    """抓拍存在但 LLM 未返回有效框：清空框并标记未对齐，避免展示误导性置信度。"""
    from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

    out = dict(payload)
    out["source_width"] = source_width
    out["source_height"] = source_height
    out["snapshot_mismatch"] = True
    out["boxes"] = []
    out["snapshot_aligned"] = True
    out.pop("display_confidence", None)
    out["judgment_note"] = "抓拍与检测未对齐"
    out.pop("llm_description", None)
    out.pop("judgment_source", None)
    return align_detection_payload_to_snapshot(event_id, out)


def _collect_vaio_llm_hits_for_equipment(equipment_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
    """从 VAIO 业务日志收集某设备近期 LLM 检测（含 bbox）。"""
    eid = (equipment_id or "").strip()
    if not eid:
        return []
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for log_path in _vaio_log_paths():
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if eid not in line or "CComponentLLMEng::DetectImg" not in line:
                continue
            marker = "http response:"
            pos = line.find(marker)
            if pos < 0:
                continue
            payload = line[pos + len(marker) :].strip()
            if ", task id:" in payload:
                payload = payload.rsplit(", task id:", 1)[0].strip()
            if payload.endswith(","):
                payload = payload[:-1]
            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for img in body.get("processedImages") or []:
                if not isinstance(img, dict):
                    continue
                for det in img.get("detections") or []:
                    if not isinstance(det, dict) or not det.get("bbox"):
                        continue
                    key = json.dumps(det, sort_keys=True, ensure_ascii=False)
                    if key in seen:
                        continue
                    seen.add(key)
                    frame_ms: int | None = None
                    raw_name = img.get("image_name")
                    try:
                        if raw_name is not None and str(raw_name).strip().isdigit():
                            frame_ms = int(str(raw_name).strip())
                    except (TypeError, ValueError):
                        frame_ms = None
                    hits.append(
                        {
                            "confidence": det.get("confidence"),
                            "class_name": str(det.get("class_name") or "").strip(),
                            "description": str(det.get("description") or "").strip(),
                            "bbox": det.get("bbox"),
                            "frame_ms": frame_ms,
                            "source": "vaio_log_equipment",
                        }
                    )
                    if len(hits) >= limit:
                        return hits
    return hits


def refill_event_detection_boxes(
    event_id: str,
    detection_json: str,
    *,
    detecttype: int | None,
    params: dict[str, Any] | None = None,
    llm_hit: dict[str, Any] | None = None,
    force_snapshot_align: bool = False,
) -> str:
    """对缺少 boxes 的事件，用已存抓拍或 LLM 命中补全检测框；可对齐到取证抓拍。"""
    from inspection_platform.inspection_event.evidence import snapshot_file, _jpeg_dimensions

    payload: dict[str, Any] = {}
    raw = (detection_json or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    has_boxes = isinstance(payload.get("boxes"), list) and bool(payload["boxes"])
    snapshot_aligned = bool(payload.get("snapshot_aligned"))
    judgment_source = str(payload.get("judgment_source") or "").strip()
    snap_path = snapshot_file(event_id)
    p = dict(params or {})
    w = int(payload.get("source_width") or 1280)
    h = int(payload.get("source_height") or 720)

    need_snapshot_llm = snap_path.is_file() and (
        force_snapshot_align or not has_boxes or not snapshot_aligned
    )
    equipment_id = str(payload.get("equipment_id") or "").strip()

    if (
        judgment_source == "snapshot_llm"
        and has_boxes
        and snapshot_aligned
        and snap_path.is_file()
    ):
        from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

        payload = align_detection_payload_to_snapshot(event_id, payload)
        payload = _normalize_detection_box_labels(payload, detecttype)
        return json.dumps(payload, ensure_ascii=False)

    if need_snapshot_llm:
        w, h = _jpeg_dimensions(snap_path)
        if not is_main_hd_frame(w, h):
            logger.warning(
                "跳过低分辨率抓拍 LLM 复核 event_id=%s size=%dx%d",
                event_id,
                w,
                h,
            )
            need_snapshot_llm = False
    if need_snapshot_llm:
        w, h = _jpeg_dimensions(snap_path)
        image_name_ms = _plausible_image_name_ms(payload.get("frame_ms"))
        hits = _call_llm_process_rule(
            image_path=str(snap_path),
            image_name_ms=image_name_ms,
            detecttype=detecttype,
            threshold=_llm_confidence_threshold(p),
        )
        valid = [hit for hit in hits if _is_valid_llm_hit(hit, detecttype)]
        if valid:
            best = max(valid, key=lambda item: float(item.get("confidence") or 0))
            payload = _apply_snapshot_llm_hit(
                payload,
                best,
                event_id=event_id,
                source_width=w,
                source_height=h,
                detecttype=detecttype,
            )
            payload = _normalize_detection_box_labels(payload, detecttype)
            return json.dumps(payload, ensure_ascii=False)
        if force_snapshot_align:
            if has_boxes:
                from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

                payload = align_detection_payload_to_snapshot(event_id, payload)
                payload["source_width"] = w
                payload["source_height"] = h
                payload["snapshot_aligned"] = True
                payload.pop("snapshot_mismatch", None)
                payload.pop("judgment_note", None)
                if not str(payload.get("judgment_source") or "").strip():
                    payload["judgment_source"] = "vaio_alert_frame"
                if payload.get("display_confidence") is None:
                    confs: list[float] = []
                    for box in payload.get("boxes") or []:
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
                payload = _normalize_detection_box_labels(payload, detecttype)
                return json.dumps(payload, ensure_ascii=False)
            payload = _mark_snapshot_detection_mismatch(
                payload,
                event_id=event_id,
                source_width=w,
                source_height=h,
            )
            return json.dumps(payload, ensure_ascii=False)

    if not has_boxes and equipment_id and not snap_path.is_file():
        log_hits = _collect_vaio_llm_hits_for_equipment(equipment_id)
        valid_log = [h for h in log_hits if _is_valid_llm_hit(h, detecttype)]
        if valid_log:
            best = max(valid_log, key=lambda item: float(item.get("confidence") or 0))
            snap_w = int(payload.get("source_width") or w)
            snap_h = int(payload.get("source_height") or h)
            ref_w, ref_h = snap_w, snap_h
            patch_json = _detection_json_from_llm_hit(
                best,
                detecttype=detecttype,
                source_width=snap_w,
                source_height=snap_h,
                bbox_reference_width=ref_w,
                bbox_reference_height=ref_h,
            )
            if patch_json:
                patch = json.loads(patch_json)
                payload = _merge_detection_payload(payload, patch)
                payload["source_width"] = snap_w
                payload["source_height"] = snap_h
                payload["snapshot_aligned"] = True
                payload.pop("snapshot_mismatch", None)
                from inspection_platform.inspection_event.evidence import (
                    align_detection_payload_to_snapshot,
                )

                payload = align_detection_payload_to_snapshot(event_id, payload)
                payload = _normalize_detection_box_labels(payload, detecttype)
                return json.dumps(payload, ensure_ascii=False)

    if has_boxes and snapshot_aligned:
        from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

        payload = align_detection_payload_to_snapshot(event_id, payload)
        payload = _normalize_detection_box_labels(payload, detecttype)
        return json.dumps(payload, ensure_ascii=False)

    if llm_hit and not snap_path.is_file():
        xyxy = _parse_bbox_to_xyxy(llm_hit.get("bbox"), source_width=w, source_height=h)
        if xyxy:
            x1, y1, x2, y2 = xyxy
            conf = llm_hit.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            payload = _merge_detection_payload(
                payload,
                {
                    "source_width": w,
                    "source_height": h,
                    "boxes": [
                        _box_from_xyxy(
                            x1,
                            y1,
                            x2,
                            y2,
                            label=_llm_hit_box_label(llm_hit, detecttype),
                            confidence=conf_f,
                        )
                    ],
                },
            )
            from inspection_platform.inspection_event.evidence import (
                align_detection_payload_to_snapshot,
            )

            payload = align_detection_payload_to_snapshot(event_id, payload)
            payload = _normalize_detection_box_labels(payload, detecttype)
            return json.dumps(payload, ensure_ascii=False)

    if has_boxes:
        from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

        payload = align_detection_payload_to_snapshot(event_id, payload)
        payload = _normalize_detection_box_labels(payload, detecttype)
        return json.dumps(payload, ensure_ascii=False)

    if snap_path.is_file() and not need_snapshot_llm:
        w, h = _jpeg_dimensions(snap_path)
        image_name_ms = _plausible_image_name_ms(payload.get("frame_ms"))
        hits = _call_llm_process_rule(
            image_path=str(snap_path),
            image_name_ms=image_name_ms,
            detecttype=detecttype,
            threshold=_llm_confidence_threshold(p),
        )
        valid = [hit for hit in hits if _is_valid_llm_hit(hit, detecttype)]
        if valid:
            best = max(valid, key=lambda item: float(item.get("confidence") or 0))
            payload = _apply_snapshot_llm_hit(
                payload,
                best,
                event_id=event_id,
                source_width=w,
                source_height=h,
                detecttype=detecttype,
            )
            payload = _normalize_detection_box_labels(payload, detecttype)
            return json.dumps(payload, ensure_ascii=False)

    if snap_path.is_file() and payload:
        from inspection_platform.inspection_event.evidence import align_detection_payload_to_snapshot

        payload = align_detection_payload_to_snapshot(event_id, payload)
        payload = _normalize_detection_box_labels(payload, detecttype)
        return json.dumps(payload, ensure_ascii=False)

    return detection_json if payload else detection_json


def _detection_json_from_llm_hit(
    hit: dict[str, Any],
    *,
    detecttype: int | None = None,
    video_duration_sec: float | None = None,
    source_width: int = 1280,
    source_height: int = 720,
    bbox_reference_width: int | None = None,
    bbox_reference_height: int | None = None,
) -> str:
    ref_w = max(1, int(bbox_reference_width or source_width))
    ref_h = max(1, int(bbox_reference_height or source_height))
    out_w = max(1, int(source_width))
    out_h = max(1, int(source_height))
    xyxy = _parse_bbox_to_xyxy(
        hit.get("bbox"),
        source_width=ref_w,
        source_height=ref_h,
    )
    if xyxy and (ref_w != out_w or ref_h != out_h):
        x1, y1, x2, y2 = xyxy
        sx = out_w / ref_w
        sy = out_h / ref_h
        xyxy = (x1 * sx, y1 * sy, x2 * sx, y2 * sy)
    if not xyxy:
        return ""
    x1, y1, x2, y2 = xyxy
    conf = hit.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None
    frame_ms = hit.get("frame_ms")
    vts = hit.get("video_time_sec")
    if vts is None and isinstance(frame_ms, int) and video_duration_sec:
        vts = _video_time_from_frame_ms(frame_ms, video_duration_sec)
    payload: dict[str, Any] = {
        "source_width": out_w,
        "source_height": out_h,
        "boxes": [
            _box_from_xyxy(
                x1,
                y1,
                x2,
                y2,
                label=_llm_hit_box_label(hit, detecttype),
                confidence=conf_f,
            )
        ],
    }
    if isinstance(frame_ms, int) and 0 < frame_ms < 3_600_000:
        payload["frame_ms"] = frame_ms
    if vts is not None:
        try:
            v = float(vts)
            if 0 <= v <= 3600:
                payload["video_time_sec"] = round(v, 3)
        except (TypeError, ValueError):
            pass
    if video_duration_sec and video_duration_sec > 0:
        payload["video_duration_sec"] = round(float(video_duration_sec), 3)
    return json.dumps(payload, ensure_ascii=False)


def _detection_json_from_vaio_raw(
    raw: dict[str, Any],
    *,
    source_width: int = 1280,
    source_height: int = 720,
) -> str:
    boxes: list[dict[str, Any]] = []

    def _append_box(item: dict[str, Any]) -> bool:
        xyxy = _parse_bbox_to_xyxy(
            item.get("bbox") or item.get("box") or item.get("rect") or item.get("rectangle"),
            source_width=source_width,
            source_height=source_height,
        )
        if xyxy:
            x1, y1, x2, y2 = xyxy
            conf = item.get("confidence", item.get("score"))
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            boxes.append(
                _box_from_xyxy(
                    x1,
                    y1,
                    x2,
                    y2,
                    label=str(item.get("label") or item.get("type") or item.get("class_name") or "").strip(),
                    confidence=conf_f,
                )
            )
            return True
        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
            w = float(item.get("width", item.get("w", 0)))
            h = float(item.get("height", item.get("h", 0)))
        except (TypeError, ValueError):
            return False
        if w <= 0 or h <= 0:
            return False
        conf = item.get("confidence", item.get("score"))
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        boxes.append(
            {
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "label": str(item.get("label") or item.get("type") or "").strip(),
                "confidence": conf_f,
            }
        )
        return True

    top_xyxy = _parse_bbox_to_xyxy(
        raw.get("bbox") or raw.get("box") or raw.get("rect") or raw.get("rectangle"),
        source_width=source_width,
        source_height=source_height,
    )
    if top_xyxy:
        x1, y1, x2, y2 = top_xyxy
        conf = raw.get("confidence", raw.get("score"))
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        boxes.append(
            _box_from_xyxy(
                x1,
                y1,
                x2,
                y2,
                label=str(raw.get("label") or raw.get("type") or raw.get("class_name") or "").strip(),
                confidence=conf_f,
            )
        )

    for key in ("context", "objects", "detections", "boxes"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                continue
        if not isinstance(val, list):
            continue
        for item in val:
            if not isinstance(item, dict):
                continue
            _append_box(item)
        if boxes:
            break
    if not boxes:
        return ""
    return json.dumps(
        {"source_width": source_width, "source_height": source_height, "boxes": boxes},
        ensure_ascii=False,
    )


def _detection_json_merged(
    *,
    llm_hit: dict[str, Any] | None,
    vaio_raw: dict[str, Any] | None,
    video_duration_sec: float | None,
    source_width: int,
    source_height: int,
    detecttype: int | None = None,
) -> str:
    """优先 LLM 置信度/时间，检测框优先 VAIO 姿态链路（与 C++ upload 一致）。"""
    if vaio_raw:
        vaio_json = _detection_json_from_vaio_raw(
            vaio_raw, source_width=source_width, source_height=source_height
        )
        if vaio_json and llm_hit:
            try:
                data = json.loads(vaio_json)
                conf = llm_hit.get("confidence")
                if conf is not None and data.get("boxes"):
                    data["boxes"][0]["confidence"] = float(conf)
                    data["boxes"][0]["label"] = _llm_hit_box_label(llm_hit, detecttype)
                vts = llm_hit.get("video_time_sec")
                if vts is not None:
                    data["video_time_sec"] = round(float(vts), 3)
                frame_ms = llm_hit.get("frame_ms")
                if isinstance(frame_ms, int) and frame_ms > 0:
                    data["frame_ms"] = frame_ms
                if video_duration_sec and video_duration_sec > 0:
                    data["video_duration_sec"] = round(float(video_duration_sec), 3)
                return json.dumps(data, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if vaio_json:
            return vaio_json
    if llm_hit:
        return _detection_json_from_llm_hit(
            llm_hit,
            detecttype=detecttype,
            video_duration_sec=video_duration_sec,
            source_width=source_width,
            source_height=source_height,
        )
    return ""


class InspectionWorkRunner:
    def __init__(self) -> None:
        self._work_svc = None
        self._event_svc = InspectionEventService()
        self._equip_svc = EquipmentService()
        self._algo_svc = AlgorithmService()
        self._region_svc = RegionMetaService()
        self._event_svc.ensure_ready()
        self._equip_svc.ensure_ready()
        self._algo_svc.ensure_ready()

    def _work_service(self):
        if self._work_svc is None:
            from inspection_platform.inspection_work.service import InspectionWorkService

            svc = InspectionWorkService()
            svc.ensure_ready()
            self._work_svc = svc
        return self._work_svc

    def run_manual(self, work_id: str) -> dict[str, Any]:
        wid = work_id.strip()
        logger.info("开始手动执行业务 work_id=%s", wid)
        work = self._work_service().get(wid)
        if not work:
            logger.warning("业务不存在 work_id=%s", wid)
            raise ValueError("巡检业务不存在")
        if str(work.get("schedule_mode") or "") != "manual":
            logger.warning(
                "非手动触发模式 work_id=%s schedule_mode=%s",
                wid,
                work.get("schedule_mode"),
            )
            raise ValueError("仅「手动触发」运行周期的业务可手动执行")
        if str(work.get("work_status") or "online") == "offline":
            logger.warning("业务已下线 work_id=%s", wid)
            raise ValueError("业务已下线，请先上线后再触发")
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        tracking = WorkTrackingService()
        tracking.require_published_for_manual(wid)
        tracking.mark_running(wid)
        try:
            result = self._execute_work(work, analysis_window_sec=None)
            tracking.mark_completed(wid)
            return result
        except Exception:
            raise

    def run_continuous_tick(self, work_id: str) -> dict[str, Any]:
        """持续监控单 tick：分析前 CONTINUOUS_ANALYSIS_WINDOW_SEC 秒画面。"""
        wid = work_id.strip()
        work = self._work_service().get(wid)
        if not work:
            logger.warning("持续监控业务不存在 work_id=%s", wid)
            raise ValueError("巡检业务不存在")
        if str(work.get("schedule_mode") or "") != "continuous":
            raise ValueError("非持续监控模式")
        if str(work.get("work_status") or "online") == "offline":
            return {
                "work_id": wid,
                "skipped": True,
                "reason": "offline",
                "tasks": [],
                "events_created": 0,
                "events": [],
                "warnings": [],
            }
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        tracking = WorkTrackingService()
        if not tracking.is_published(wid):
            return {
                "work_id": wid,
                "skipped": True,
                "reason": "not_published",
                "tasks": [],
                "events_created": 0,
                "events": [],
                "warnings": [],
            }
        tracking.ensure_running_for_continuous(wid)
        logger.info(
            "持续监控 tick work_id=%s window=%ss interval=%ss",
            wid,
            CONTINUOUS_ANALYSIS_WINDOW_SEC,
            CONTINUOUS_CHECK_INTERVAL_SEC,
        )
        return self._execute_work(work, analysis_window_sec=CONTINUOUS_ANALYSIS_WINDOW_SEC)

    def run_scheduled_tick(self, work_id: str) -> dict[str, Any]:
        """周期/定时检查单窗口：在追踪进入 running 后执行一轮完整分析。"""
        wid = work_id.strip()
        work = self._work_service().get(wid)
        if not work:
            logger.warning("周期/定时业务不存在 work_id=%s", wid)
            raise ValueError("巡检业务不存在")
        mode = str(work.get("schedule_mode") or "")
        if mode not in ("periodic", "scheduled"):
            raise ValueError("非周期/定时检查模式")
        if str(work.get("work_status") or "online") == "offline":
            return {
                "work_id": wid,
                "skipped": True,
                "reason": "offline",
                "tasks": [],
                "events_created": 0,
                "events": [],
                "warnings": [],
            }
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        tracking = WorkTrackingService()
        if not tracking.is_published(wid):
            return {
                "work_id": wid,
                "skipped": True,
                "reason": "not_published",
                "tasks": [],
                "events_created": 0,
                "events": [],
                "warnings": [],
            }
        row = tracking.get(wid) or {}
        if str(row.get("queue_status") or "") != "running":
            return {
                "work_id": wid,
                "skipped": True,
                "reason": "not_running",
                "tasks": [],
                "events_created": 0,
                "events": [],
                "warnings": [],
            }
        logger.info(
            "周期/定时窗口执行 work_id=%s mode=%s name=%s",
            wid,
            mode,
            work.get("name"),
        )
        return self._execute_work(work, analysis_window_sec=None)

    def _execute_work(
        self,
        work: dict[str, Any],
        *,
        analysis_window_sec: float | None,
    ) -> dict[str, Any]:
        wid = str(work.get("work_id") or "").strip()
        equipment_set = work.get("equipment_set") or []
        algorithm_set = work.get("algorithm_set") or []
        if not equipment_set:
            raise ValueError("请先配置至少一台设备")
        if not algorithm_set:
            raise ValueError("请先配置至少一个算法")

        logger.info(
            "业务配置 work_id=%s name=%s equipments=%d algorithms=%d window=%s",
            wid,
            work.get("name"),
            len(equipment_set),
            len(algorithm_set),
            analysis_window_sec,
        )

        algo_params_all = work.get("equipment_algo_params") or {}
        region_names = _region_name_map(self._region_svc)
        rule_name = ""
        rules = work.get("rule_set") or []
        if rules and isinstance(rules[0], dict):
            rule_name = str(rules[0].get("name") or "")

        tasks: list[dict[str, Any]] = []
        created_events: list[dict[str, Any]] = []
        warnings: list[str] = []

        for equip in equipment_set:
            if not isinstance(equip, dict):
                continue
            equipment_id = str(equip.get("equipment_id") or "").strip()
            if not equipment_id:
                continue
            equip_row = self._equip_svc.get(equipment_id)
            if not equip_row:
                msg = f"设备 {equipment_id} 不存在，已跳过"
                logger.warning("跳过设备 work_id=%s equipment_id=%s reason=not_found", wid, equipment_id)
                warnings.append(msg)
                continue
            equip_name = str(equip.get("name") or equip_row.get("name") or equipment_id)
            region_id = str(equip_row.get("region_id") or work.get("region_id") or "")
            region_name = region_names.get(region_id, region_id)

            for algo in algorithm_set:
                if not isinstance(algo, dict):
                    continue
                algo_id = str(algo.get("algorithm_id") or "").strip()
                algo_name = str(algo.get("name") or algo_id)
                if not algo_id:
                    continue
                params = algo_params_all.get(equipment_id, {}).get(algo_id, {})
                if not isinstance(params, dict):
                    params = {}
                if not _is_algo_enabled(params):
                    msg = f"{equip_name} · {algo_name} 已禁用，已跳过"
                    logger.info(
                        "跳过已禁用算法 work_id=%s equipment=%s algorithm=%s",
                        wid,
                        equipment_id,
                        algo_id,
                    )
                    warnings.append(msg)
                    continue

                kind = str(equip_row.get("kind") or equip.get("role") or "camera")
                logger.info(
                    "执行子任务 work_id=%s equipment=%s(%s) algorithm=%s(%s) kind=%s",
                    wid,
                    equipment_id,
                    equip_name,
                    algo_id,
                    algo_name,
                    kind,
                )
                try:
                    if kind == "sensor" or algo_id == "algo-4":
                        ev = self._run_sensor_job(
                            work=work,
                            equipment_id=equipment_id,
                            equip_name=equip_name,
                            region_id=region_id,
                            region_name=region_name,
                            algo_id=algo_id,
                            algo_name=algo_name,
                            rule_name=rule_name,
                            params=params,
                        )
                        tasks.append({"equipment_id": equipment_id, "algorithm_id": algo_id, "mode": "sensor"})
                        if ev:
                            created_events.append(ev)
                    else:
                        task_result, events = self._run_video_job(
                            work=work,
                            equipment_id=equipment_id,
                            equip_name=equip_name,
                            region_id=region_id,
                            region_name=region_name,
                            algo_id=algo_id,
                            algo_name=algo_name,
                            rule_name=rule_name,
                            params=params,
                            analysis_window_sec=analysis_window_sec,
                        )
                        tasks.append(task_result)
                        created_events.extend(events)
                        logger.info(
                            "子任务完成 work_id=%s equipment=%s algorithm=%s mode=%s events=%d",
                            wid,
                            equipment_id,
                            algo_id,
                            task_result.get("mode"),
                            len(events),
                        )
                except Exception as e:
                    logger.exception(
                        "子任务失败 work_id=%s equipment=%s algorithm=%s",
                        wid,
                        equipment_id,
                        algo_id,
                    )
                    warnings.append(f"{equip_name} · {algo_name}：{e}")

        logger.info(
            "业务执行结束 work_id=%s tasks=%d events_created=%d warnings=%d",
            wid,
            len(tasks),
            len(created_events),
            len(warnings),
        )
        return {
            "work_id": wid,
            "tasks": tasks,
            "events_created": len(created_events),
            "events": created_events,
            "warnings": warnings,
        }

    def _run_sensor_job(
        self,
        *,
        work: dict[str, Any],
        equipment_id: str,
        equip_name: str,
        region_id: str,
        region_name: str,
        algo_id: str,
        algo_name: str,
        rule_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        readings, _ = self._equip_svc.list_readings(equipment_id, limit=1)
        if not readings:
            raise ValueError("传感器暂无读数")
        latest = readings[0]
        value = float(latest.get("value") or 0)
        threshold = float(params.get("threshold", 70))
        unit = str(self._equip_svc.get(equipment_id).get("unit") or "")
        if value < threshold:
            logger.info(
                "传感器未超阈值 equipment=%s value=%s threshold=%s",
                equipment_id,
                value,
                threshold,
            )
            return None
        ev = self._event_svc.create(
            kind="sensor",
            title=f"{algo_name}超阈值",
            source_name=equip_name,
            work_id=str(work.get("work_id") or ""),
            work_name=str(work.get("name") or ""),
            region_id=region_id,
            region_name=region_name,
            equipment_id=equipment_id,
            algorithm_name=algo_name,
            rule_name=rule_name,
            status="pending",
            value_num=value,
            threshold_text=f"阈值 {threshold}{unit}",
            snapshot_gradient=_event_gradient("sensor"),
            occurred_at=_utc_now(),
            reported_at=_utc_now(),
        )
        logger.info(
            "传感器告警入库 equipment=%s event_id=%s value=%s",
            equipment_id,
            ev.get("event_id"),
            value,
        )
        return ev

    def _run_video_job(
        self,
        *,
        work: dict[str, Any],
        equipment_id: str,
        equip_name: str,
        region_id: str,
        region_name: str,
        algo_id: str,
        algo_name: str,
        rule_name: str,
        params: dict[str, Any],
        analysis_window_sec: float | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        detecttype = _parse_vaio_detecttype(algo_id, self._algo_svc, algo_name=algo_name)
        video_url, src_data_type = _resolve_video_source(self._equip_svc, equipment_id)
        original_video_path = video_url
        camera_rtsp = video_url if src_data_type == 1 else ""
        rtsp_url = camera_rtsp
        if src_data_type == 1 and camera_rtsp:
            from inspection_platform.media.service import get_media_service

            analysis_url = get_media_service().analysis_rtsp_url(equipment_id, camera_rtsp)
            if analysis_url != camera_rtsp:
                logger.info(
                    "VAIO 分析改走 go2rtc 单路拉流 equipment=%s relay=%s",
                    equipment_id,
                    analysis_url,
                )
                video_url = analysis_url
        temp_clip: str | None = None
        window_meta: dict[str, Any] = {}
        try:
            if analysis_window_sec and analysis_window_sec > 0:
                win = float(analysis_window_sec)
                if src_data_type == 2 and os.path.isfile(video_url):
                    full_duration = _probe_video_duration_sec(video_url) or win
                    start_sec, seg_dur = _continuous_window_on_file(full_duration, win)
                    temp_clip = _extract_video_clip(
                        video_url, start_sec=start_sec, duration_sec=seg_dur
                    )
                    video_url = temp_clip
                    window_meta = {
                        "analysis_window_sec": win,
                        "window_start_sec": round(start_sec, 3),
                        "window_duration_sec": round(seg_dur, 3),
                    }
                    logger.info(
                        "持续监控截取窗口 equipment=%s start=%.1fs dur=%.1fs",
                        equipment_id,
                        start_sec,
                        seg_dur,
                    )
                elif src_data_type == 1:
                    window_meta = {"analysis_window_sec": win, "stream": "live"}

            evidence_ctx = {
                "analysis_video_path": video_url,
                "original_video_path": original_video_path if temp_clip else "",
                "window_start_sec": float(window_meta.get("window_start_sec") or 0.0),
                "is_analysis_clip": bool(temp_clip),
                "src_data_type": src_data_type,
                "rtsp_url": rtsp_url,
            }

            algo_row = self._algo_svc.get(algo_id)
            algo_schema = algo_row.get("schema") if isinstance(algo_row, dict) else None
            from inspection_platform.algorithm.llm_detect_client import resolve_llm_direct_config

            llm_direct = resolve_llm_direct_config(
                algo_id,
                algo_name,
                algo_schema if isinstance(algo_schema, dict) else None,
            )
            if llm_direct:
                task_id = f"iw-{work.get('work_id')}-{equipment_id}-{algo_id}-{int(time.time())}"
                logger.info(
                    "大模型直连检测 task_id=%s algorithm=%s kind=%s video=%s",
                    task_id,
                    algo_id,
                    llm_direct.get("kind"),
                    video_url,
                )
                task_result, events = self._run_llm_direct_video(
                    task_id=task_id,
                    work=work,
                    equipment_id=equipment_id,
                    equip_name=equip_name,
                    region_id=region_id,
                    region_name=region_name,
                    algo_id=algo_id,
                    algo_name=algo_name,
                    rule_name=rule_name,
                    params=params,
                    video_url=video_url,
                    src_data_type=src_data_type,
                    llm_config=llm_direct,
                    analysis_window_sec=analysis_window_sec,
                    evidence_ctx=evidence_ctx,
                )
                if window_meta:
                    task_result.update(window_meta)
                return task_result, events

            task_id = f"iw-{work.get('work_id')}-{equipment_id}-{algo_id}-{int(time.time())}"
            config = _build_vaio_config(params, detecttype=detecttype)

            from inspection_platform.algorithm import vaio_client

            vaio_ok = vaio_client.core_available()
            engine_note = ""
            if detecttype in _POSE_FALL_DETECTTYPES:
                engine_note = (
                    " engines=detection:yolov5m_person.engine(modelid=4)+pose:hrnet.engine(modelid=5)"
                )
            logger.info(
                "视频任务准备 task_id=%s detecttype=%s video=%s src_type=%s vaio_core=%s config=%s%s",
                task_id,
                detecttype,
                video_url,
                src_data_type,
                vaio_ok,
                _vaio_config_log_summary(config),
                engine_note,
            )

            if detecttype is not None and vaio_ok:
                task_result, events = self._run_vaio_video(
                    task_id=task_id,
                    detecttype=detecttype,
                    video_url=video_url,
                    src_data_type=src_data_type,
                    config=config,
                    work=work,
                    equipment_id=equipment_id,
                    equip_name=equip_name,
                    region_id=region_id,
                    region_name=region_name,
                    algo_id=algo_id,
                    algo_name=algo_name,
                    rule_name=rule_name,
                    params=params,
                    analysis_window_sec=analysis_window_sec,
                    evidence_ctx=evidence_ctx,
                )
                if window_meta:
                    task_result.update(window_meta)
                return task_result, events

            if detecttype == 1018 and not vaio_ok:
                logger.error("VAIO 核心不可用，无法执行摔倒算法 task_id=%s", task_id)
                raise RuntimeError(
                    "卧倒摔倒识别需 VAIO 核心（:9200）在线，请先启动 vaio-analysis-core"
                )

            logger.warning(
                "降级为占位推理 task_id=%s detecttype=%s vaio_core=%s",
                task_id,
                detecttype,
                vaio_ok,
            )
            task_result, events = self._run_mock_video(
                task_id=task_id,
                work=work,
                equipment_id=equipment_id,
                equip_name=equip_name,
                region_id=region_id,
                region_name=region_name,
                algo_id=algo_id,
                algo_name=algo_name,
                rule_name=rule_name,
                params=params,
                vaio_available=vaio_client.core_available(),
                detecttype=detecttype,
                evidence_ctx=evidence_ctx,
            )
            if window_meta:
                task_result.update(window_meta)
            return task_result, events
        finally:
            if temp_clip and os.path.isfile(temp_clip):
                try:
                    os.unlink(temp_clip)
                except OSError:
                    pass

    def _video_event_evidence_acceptable(self, parsed: dict[str, Any] | None) -> bool:
        """直播事件：抓拍 URL、检测框与 snapshot LLM 校验均须齐备。"""
        if not isinstance(parsed, dict):
            return False
        if parsed.get("snapshot_mismatch"):
            return False
        boxes = parsed.get("boxes")
        if not isinstance(boxes, list) or not boxes:
            return False
        if not str(parsed.get("snapshot_url") or "").strip():
            return False
        return str(parsed.get("judgment_source") or "") in ("snapshot_llm", "vaio_alert_frame")

    def _reject_inaccurate_video_event(
        self,
        ev: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        eid = str(ev.get("event_id") or "").strip()
        if not eid:
            return
        logger.warning("取证未对齐，丢弃事件 event_id=%s reason=%s", eid, reason)
        self._event_svc.delete(eid)

    def _finalize_video_event(
        self,
        ev: dict[str, Any],
        evidence_ctx: dict[str, Any],
        *,
        detecttype: int | None = None,
        params: dict[str, Any] | None = None,
        llm_hit: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        from inspection_platform.inspection_event.evidence import (
            attach_alert_frame_evidence,
            attach_detection_evidence,
            attach_rtsp_snapshot_to_event,
            snapshot_file,
        )

        eid = str(ev.get("event_id") or "").strip()
        if not eid:
            return ev
        dj = str(ev.get("detection_json") or "")
        ctx = dict(evidence_ctx or {})
        eq_id = str(ev.get("equipment_id") or ctx.get("equipment_id") or "").strip()
        ctx["equipment_id"] = eq_id
        rtsp = str(ctx.get("rtsp_url") or "").strip()
        if not rtsp and int(ctx.get("src_data_type") or 0) == 1:
            rtsp = str(ctx.get("analysis_video_path") or "").strip()

        alert_bytes = ctx.get("alert_snapshot_bytes")
        video_time_sec: float | None = None
        if ctx.get("alert_video_time_sec") is not None:
            try:
                video_time_sec = float(ctx["alert_video_time_sec"])
            except (TypeError, ValueError):
                video_time_sec = None
        if video_time_sec is None and dj.strip():
            try:
                parsed_vts = json.loads(dj)
                if isinstance(parsed_vts, dict) and parsed_vts.get("video_time_sec") is not None:
                    video_time_sec = float(parsed_vts["video_time_sec"])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        if isinstance(alert_bytes, bytes) and len(alert_bytes) > 256:
            updated = attach_alert_frame_evidence(
                eid,
                alert_bytes,
                dj,
                video_time_sec=video_time_sec,
            )
        elif dj.strip():
            updated = attach_detection_evidence(eid, dj, ctx)
        elif rtsp:
            updated = attach_rtsp_snapshot_to_event(
                eid, dj, rtsp, equipment_id=eq_id,
            )
        else:
            updated = dj

        if eq_id:
            try:
                parsed_eq = json.loads(updated) if updated.strip() else {}
                if not isinstance(parsed_eq, dict):
                    parsed_eq = {}
                parsed_eq["equipment_id"] = eq_id
                updated = json.dumps(parsed_eq, ensure_ascii=False)
            except json.JSONDecodeError:
                updated = json.dumps({"equipment_id": eq_id}, ensure_ascii=False)

        updated = refill_event_detection_boxes(
            eid,
            updated,
            detecttype=detecttype,
            params=params,
            llm_hit=None if snapshot_file(eid).is_file() else llm_hit,
            force_snapshot_align=True,
        )

        try:
            parsed_updated = json.loads(updated) if updated.strip() else {}
        except json.JSONDecodeError:
            parsed_updated = {}
        got_boxes = isinstance(parsed_updated, dict) and bool(parsed_updated.get("boxes"))
        snapshot_mismatch = isinstance(parsed_updated, dict) and bool(
            parsed_updated.get("snapshot_mismatch")
        )
        if snapshot_mismatch or (
            int(ctx.get("src_data_type") or 0) == 1
            and not self._video_event_evidence_acceptable(parsed_updated)
        ):
            note = ""
            if isinstance(parsed_updated, dict):
                note = str(parsed_updated.get("judgment_note") or "").strip()
            self._reject_inaccurate_video_event(
                ev,
                reason=note or "抓拍与检测未对齐",
            )
            return None
        if updated == dj and not got_boxes:
            return ev
        row = self._event_svc.update_detection_json(eid, updated)
        if isinstance(parsed_updated, dict):
            from inspection_platform.inspection_event.service import (
                _resolution_detail_from_detection_payload,
            )

            detail = _resolution_detail_from_detection_payload(
                parsed_updated,
                prior_detail=str(ev.get("resolution_detail") or ""),
            )
            if detail is not None:
                row = self._event_svc.update(eid, resolution_detail=detail) or row
        return row if row else ev

    def _run_vaio_video(
        self,
        *,
        task_id: str,
        detecttype: int,
        video_url: str,
        src_data_type: int,
        config: dict[str, Any],
        work: dict[str, Any],
        equipment_id: str,
        equip_name: str,
        region_id: str,
        region_name: str,
        algo_id: str,
        algo_name: str,
        rule_name: str,
        params: dict[str, Any],
        analysis_window_sec: float | None = None,
        evidence_ctx: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        from inspection_platform.algorithm import vaio_client

        ctx = dict(evidence_ctx or {})
        if not ctx.get("analysis_video_path"):
            ctx["analysis_video_path"] = video_url
        if "src_data_type" not in ctx:
            ctx["src_data_type"] = src_data_type

        video_duration_sec: float | None = None
        source_width, source_height = 1280, 720
        if src_data_type == 1:
            source_width, source_height = _VAIO_LIVE_REF_WIDTH, _VAIO_LIVE_REF_HEIGHT
        elif src_data_type == 2 or not str(video_url).startswith(("http://", "https://", "rtsp://")):
            video_duration_sec = _probe_video_duration_sec(video_url)
            source_width, source_height = _probe_video_dimensions(video_url)
            if video_duration_sec:
                logger.info(
                    "视频 probe task_id=%s duration_sec=%.3f size=%dx%d path=%s",
                    task_id,
                    video_duration_sec,
                    source_width,
                    source_height,
                    video_url,
                )

        payload = {
            "task_id": task_id,
            "video_url": video_url,
            "src_data_type": src_data_type,
            "task_name": f"{work.get('name')}-{equip_name}-{algo_name}",
            "algorithms": [
                {
                    "detecttype": detecttype,
                    "activerec": 0,
                    "config": config,
                }
            ],
        }
        logger.info(
            "VAIO 启动任务 task_id=%s detecttype=%s payload=%s",
            task_id,
            detecttype,
            {
                "video_url": video_url,
                "src_data_type": src_data_type,
                "config": _vaio_config_log_summary(config),
            },
        )
        start = vaio_client.start_task(payload)
        if start.get("error"):
            logger.error(
                "VAIO 启动失败 task_id=%s detecttype=%s error=%s",
                task_id,
                detecttype,
                start.get("error"),
            )
            raise RuntimeError(f"VAIO 启动失败：{start.get('error')}")
        result_code = start.get("result")
        if result_code is not None and int(result_code) != 0:
            logger.error(
                "VAIO 任务创建失败 task_id=%s detecttype=%s result=%s response=%s",
                task_id,
                detecttype,
                result_code,
                start,
            )
            raise RuntimeError(
                f"VAIO 任务创建失败（detecttype={detecttype} result={result_code}）。"
                "LLM 类算法需 Algorithm 配方含 upload.suppressEnabled，"
                "请执行 vaio-analysis-service/scripts/patch-algorithm-config.sh 后重试"
            )
        logger.info("VAIO 任务已启动 task_id=%s response=%s", task_id, start)

        poll_seconds = _vaio_poll_seconds(
            params, detecttype, video_duration_sec=video_duration_sec
        )
        if analysis_window_sec and analysis_window_sec > 0:
            poll_seconds = min(poll_seconds, int(analysis_window_sec) + 15)
        if src_data_type == 2 and video_duration_sec and video_duration_sec > 0:
            # 本地 mp4 只跑一轮，避免循环回放带来片头误报
            cap = int(video_duration_sec) + 45
            if analysis_window_sec and analysis_window_sec > 0:
                cap = int(min(video_duration_sec, analysis_window_sec)) + 10
            poll_seconds = min(poll_seconds, cap)
        frame_interval = max(1, int(float(params.get("frame_interval", 5))))
        deadline = time.time() + poll_seconds
        logger.info(
            "VAIO 轮询事件 task_id=%s poll_seconds=%s frame_interval=%s fps=%s detecttype=%s",
            task_id,
            poll_seconds,
            frame_interval,
            config.get("fps"),
            detecttype,
        )
        seen: set[str] = set()
        raw_events: list[dict[str, Any]] = []
        core_lost = False
        poll_start = time.time()
        first_event_video_sec: float | None = None

        while time.time() < deadline:
            try:
                batch = vaio_client.list_events(task_id=task_id, limit=50)
            except RuntimeError as e:
                logger.warning("VAIO 拉取事件失败 task_id=%s error=%s", task_id, e)
                if not vaio_client.core_available():
                    core_lost = True
                    logger.error("VAIO 核心已不可用（可能已崩溃），task_id=%s", task_id)
                break
            batch_items = _vaio_events_list(batch)
            if batch_items:
                logger.debug(
                    "VAIO 事件批次 task_id=%s new=%d total=%d",
                    task_id,
                    len(batch_items),
                    len(raw_events),
                )
            for item in batch_items:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    seen.add(key)
                    raw_events.append(item)
            if raw_events:
                first_event_video_sec = max(0.5, time.time() - poll_start)
                ctx["alert_video_time_sec"] = first_event_video_sec
                _capture_alert_snapshot_into_ctx(ctx, equipment_id)
                logger.info(
                    "VAIO 已收到 %d 条事件，提前结束轮询 task_id=%s video_time_sec≈%.1f",
                    len(raw_events),
                    task_id,
                    first_event_video_sec,
                )
                break
            time.sleep(min(2, max(1, frame_interval)))

        stop_result = vaio_client.stop_task(task_id)
        logger.info(
            "VAIO 任务停止 task_id=%s vaio_events=%d stop=%s core_lost=%s",
            task_id,
            len(raw_events),
            stop_result,
            core_lost,
        )

        if core_lost and not raw_events:
            raise RuntimeError(
                "VAIO 核心在处理过程中崩溃（Segmentation fault），"
                "请用 scripts/run-core.sh 重启核心；若仍崩溃，确认 LD_LIBRARY_PATH 含 cudnn-8.1"
            )

        created: list[dict[str, Any]] = []
        pose_verify = detecttype in _POSE_FALL_DETECTTYPES
        if raw_events and pose_verify:
            verify_sec = first_event_video_sec or 3.0
            llm_hit: dict[str, Any] | None = None
            if src_data_type == 2 and os.path.isfile(video_url):
                llm_hit = _verify_vaio_pose_event_with_llm(
                    video_path=video_url,
                    detecttype=detecttype,
                    params=params,
                    video_time_sec=verify_sec,
                )
            if llm_hit:
                conf = float(llm_hit["confidence"])
                detail = str(llm_hit.get("description") or "").strip()
                ev = self._event_svc.create(
                    kind="video",
                    title=_alert_event_title(algo_name),
                    source_name=equip_name,
                    work_id=str(work.get("work_id") or ""),
                    work_name=str(work.get("name") or ""),
                    region_id=region_id,
                    region_name=region_name,
                    equipment_id=equipment_id,
                    algorithm_name=algo_name,
                    rule_name=rule_name,
                    status="pending",
                    value_num=conf,
                    threshold_text=_threshold_text(params, algo_id),
                    snapshot_gradient=_event_gradient("video"),
                    occurred_at=_utc_now(),
                    reported_at=_utc_now(),
                    resolution_detail=detail[:500] if detail else None,
                    detection_json=_detection_json_merged(
                        llm_hit=llm_hit,
                        vaio_raw=raw_events[0] if raw_events else None,
                        video_duration_sec=video_duration_sec,
                        source_width=source_width,
                        source_height=source_height,
                        detecttype=detecttype,
                    ),
                )
                ev = self._finalize_video_event(
                    ev, ctx, detecttype=detecttype, params=params, llm_hit=llm_hit,
                )
                if ev:
                    logger.info(
                        "VAIO 姿态告警经 LLM 复核通过 task_id=%s event_id=%s confidence=%.3f video_time_sec=%s",
                        task_id,
                        ev.get("event_id"),
                        conf,
                        llm_hit.get("video_time_sec"),
                    )
                    created.append(ev)
                else:
                    logger.warning(
                        "VAIO 姿态告警取证未对齐，已丢弃 task_id=%s confidence=%.3f",
                        task_id,
                        conf,
                    )
            else:
                logger.warning(
                    "VAIO 姿态告警未通过 LLM 复核，已过滤不入库 task_id=%s vaio_events=%d verify_sec=%.1f",
                    task_id,
                    len(raw_events),
                    verify_sec,
                )
        elif raw_events:
            for raw in raw_events:
                conf = _vaio_event_confidence(raw)
                ev = self._event_svc.create(
                    kind="video",
                    title=_vaio_event_title(raw, algo_name),
                    source_name=equip_name,
                    work_id=str(work.get("work_id") or ""),
                    work_name=str(work.get("name") or ""),
                    region_id=region_id,
                    region_name=region_name,
                    equipment_id=equipment_id,
                    algorithm_name=algo_name,
                    rule_name=rule_name,
                    status="pending",
                    value_num=conf,
                    threshold_text=_threshold_text(params, algo_id),
                    snapshot_gradient=_event_gradient("video"),
                    occurred_at=_utc_now(),
                    reported_at=_utc_now(),
                    detection_json=_detection_json_from_vaio_raw(
                        raw,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
                ev = self._finalize_video_event(ev, ctx, detecttype=detecttype, params=params)
                if ev:
                    logger.info(
                        "VAIO 告警入库 task_id=%s event_id=%s title=%s confidence=%s",
                        task_id,
                        ev.get("event_id"),
                        ev.get("title"),
                        conf,
                    )
                    created.append(ev)
                else:
                    logger.warning(
                        "VAIO 告警取证未对齐，已丢弃 task_id=%s title=%s confidence=%s",
                        task_id,
                        _vaio_event_title(raw, algo_name),
                        conf,
                    )
        else:
            llm_hit = _resolve_llm_hit_for_video(
                task_id=task_id,
                detecttype=detecttype,
                params=params,
                video_url=video_url,
                src_data_type=src_data_type,
                video_duration_sec=video_duration_sec,
            )
            if llm_hit and detecttype in _LLM_DETECTTYPES:
                ctx["alert_video_time_sec"] = llm_hit.get("video_time_sec")
                _capture_alert_snapshot_into_ctx(ctx, equipment_id)
                conf = float(llm_hit["confidence"])
                detail = str(llm_hit.get("description") or "").strip()
                ev = self._event_svc.create(
                    kind="video",
                    title=_alert_event_title(algo_name),
                    source_name=equip_name,
                    work_id=str(work.get("work_id") or ""),
                    work_name=str(work.get("name") or ""),
                    region_id=region_id,
                    region_name=region_name,
                    equipment_id=equipment_id,
                    algorithm_name=algo_name,
                    rule_name=rule_name,
                    status="pending",
                    value_num=conf,
                    threshold_text=_threshold_text(params, algo_id),
                    snapshot_gradient=_event_gradient("video"),
                    occurred_at=_utc_now(),
                    reported_at=_utc_now(),
                    resolution_detail=detail[:500] if detail else None,
                    detection_json=_detection_json_from_llm_hit(
                        llm_hit,
                        detecttype=detecttype,
                        video_duration_sec=video_duration_sec,
                        source_width=source_width,
                        source_height=source_height,
                    ),
                )
                ev = self._finalize_video_event(
                    ev, ctx, detecttype=detecttype, params=params, llm_hit=llm_hit,
                )
                if ev:
                    vts = llm_hit.get("video_time_sec")
                    if vts is None and video_duration_sec:
                        vts = _video_time_from_frame_ms(llm_hit.get("frame_ms"), video_duration_sec)
                    logger.warning(
                        "VAIO upload 未上报事件，已从 LLM 回补 task_id=%s event_id=%s confidence=%.3f video_time_sec=%s",
                        task_id,
                        ev.get("event_id"),
                        conf,
                        vts,
                    )
                    created.append(ev)
                else:
                    logger.warning(
                        "VAIO LLM 回补取证未对齐，已丢弃 task_id=%s confidence=%.3f",
                        task_id,
                        conf,
                    )
            else:
                logger.info(
                    "VAIO 无告警且 LLM 未检出阳性，跳过事件入库 task_id=%s detecttype=%s",
                    task_id,
                    detecttype,
                )

        return {
            "task_id": task_id,
            "equipment_id": equipment_id,
            "algorithm_id": algo_id,
            "algorithm_name": algo_name,
            "mode": "vaio",
            "detecttype": detecttype,
            "vaio_algorithm": f"Algorithm_{detecttype}",
            "vaio_events": len(raw_events),
            "video_url": video_url,
        }, created

    def _run_llm_direct_video(
        self,
        *,
        task_id: str,
        work: dict[str, Any],
        equipment_id: str,
        equip_name: str,
        region_id: str,
        region_name: str,
        algo_id: str,
        algo_name: str,
        rule_name: str,
        params: dict[str, Any],
        video_url: str,
        src_data_type: int,
        llm_config: dict[str, str],
        analysis_window_sec: float | None = None,
        evidence_ctx: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """LlmEngine POST /api/detect 同步检测（不经 VAIO）。"""
        from inspection_platform.algorithm.llm_detect_client import (
            bbox_to_xyxy_list,
            body_to_hits,
            body_to_review_candidates,
            detect_image,
            filter_hits_by_bbox_area,
            filter_hits_by_review,
            llm_review_enabled,
            review_detection,
            review_prompt_for_kind,
        )

        ctx = dict(evidence_ctx or {})
        kind = str(llm_config.get("kind") or "")
        prompt = str(llm_config.get("prompt") or "")
        threshold = _llm_confidence_threshold(params)

        source_width, source_height = _VAIO_LIVE_REF_WIDTH, _VAIO_LIVE_REF_HEIGHT
        video_duration_sec: float | None = None
        video_time_sec: float | None = None
        frame_ms = 0
        temp_jpg: str | None = None

        try:
            if src_data_type == 1:
                rtsp = str(ctx.get("rtsp_url") or video_url or "").strip()
                packed = _grab_main_hd_jpeg(equipment_id, rtsp)
                if not packed:
                    raise RuntimeError(
                        "直播抓帧失败或未获得1080p主码流画面（已跳过720p子码流）"
                    )
                jpeg, source_width, source_height = packed
                fd, temp_jpg = tempfile.mkstemp(suffix=".jpg", prefix="iw-llm-detect-")
                os.close(fd)
                Path(temp_jpg).write_bytes(jpeg)
                ctx["alert_snapshot_bytes"] = jpeg
                video_time_sec = 0.0
            else:
                path = video_url
                if not os.path.isfile(path):
                    raise RuntimeError(f"视频文件不存在: {path}")
                video_duration_sec = _probe_video_duration_sec(path)
                source_width, source_height = _probe_video_dimensions(path)
                if analysis_window_sec and analysis_window_sec > 0 and video_duration_sec:
                    start_sec, seg_dur = _continuous_window_on_file(
                        video_duration_sec, float(analysis_window_sec),
                    )
                    video_time_sec = start_sec + seg_dur * 0.5
                elif video_duration_sec:
                    video_time_sec = video_duration_sec * 0.5
                else:
                    video_time_sec = 1.0
                frame_ms = int(round(max(0.0, video_time_sec) * 1000))
                fd, temp_jpg = tempfile.mkstemp(suffix=".jpg", prefix="iw-llm-detect-")
                os.close(fd)
                if not _extract_video_frame_jpeg(path, video_time_sec, temp_jpg):
                    raise RuntimeError("ffmpeg 抽帧失败，无法调用大模型检测")

            body = detect_image(
                prompt=prompt,
                image_path=temp_jpg,
                image_name=f"{frame_ms or int(time.time() * 1000)}.jpg",
                model_id=str(params.get("llm_model_id") or "").strip() or None,
            )
            logger.info(
                "大模型检测完成 task_id=%s algorithm=%s success=%s has_violation=%s violations=%d",
                task_id,
                algo_id,
                body.get("success"),
                body.get("has_violation"),
                len(body.get("violations") or []),
            )
            hits = body_to_hits(
                body,
                kind=kind,
                image_name_ms=frame_ms,
                threshold=threshold,
            )
            hits = [h for h in hits if h.get("bbox")]
            ref_w_pre = int(body.get("image_width") or source_width)
            ref_h_pre = int(body.get("image_height") or source_height)
            if kind in ("play_phone", "phone_call") and hits:
                before = len(hits)
                hits = filter_hits_by_bbox_area(
                    hits,
                    ref_width=ref_w_pre,
                    ref_height=ref_h_pre,
                )
                if before and not hits:
                    logger.info(
                        "大模型检测框面积过大已过滤 task_id=%s algorithm=%s dropped=%d",
                        task_id,
                        algo_id,
                        before,
                    )
            review_meta: dict[str, Any] = {}
            review_prompt = review_prompt_for_kind(kind, prompt)
            # 复核候选：入库过滤后的 hits，或 detect 原始 violations（阈值放宽，仅用于送复核）
            review_candidates = hits or body_to_review_candidates(
                body,
                kind=kind,
                image_name_ms=frame_ms,
                threshold=0.0,
            )
            if kind in ("play_phone", "phone_call") and review_candidates:
                review_candidates = filter_hits_by_bbox_area(
                    review_candidates,
                    ref_width=ref_w_pre,
                    ref_height=ref_h_pre,
                )
            if llm_review_enabled() and body.get("success"):
                ref_w = int(body.get("image_width") or source_width)
                ref_h = int(body.get("image_height") or source_height)
                target_bboxes: list[list[float]] = []
                for h in review_candidates:
                    xyxy = bbox_to_xyxy_list(
                        h.get("bbox"),
                        ref_width=ref_w,
                        ref_height=ref_h,
                    )
                    if xyxy:
                        target_bboxes.append(xyxy)
                review_body = review_detection(
                    prompt=review_prompt,
                    image_path=temp_jpg,
                    image_name=f"{frame_ms or int(time.time() * 1000)}.jpg",
                    target_bboxes=target_bboxes if target_bboxes else None,
                    alarm_id=task_id,
                    algorithm=algo_id,
                    model_id=str(params.get("llm_model_id") or "").strip() or None,
                )
                if review_candidates and target_bboxes:
                    hits, review_meta = filter_hits_by_review(
                        review_candidates,
                        review_body,
                        ref_width=ref_w,
                        ref_height=ref_h,
                    )
                else:
                    review_meta = {
                        "verdict": str(review_body.get("verdict") or ""),
                        "has_false_alarm": bool(review_body.get("has_false_alarm")),
                        "llm_analysis": str(review_body.get("llm_analysis") or "").strip(),
                        "iou_threshold": review_body.get("iou_threshold"),
                        "false_alarm_count": len(review_body.get("false_alarms") or []),
                        "correct_count": len(review_body.get("correct_detections") or []),
                    }
                    if not review_body.get("success"):
                        review_meta["error"] = str(
                            review_body.get("error") or review_body.get("message") or "复核失败"
                        )
                    hits = []
                logger.info(
                    "大模型复核 task_id=%s algorithm=%s verdict=%s correct=%s bboxes=%d",
                    task_id,
                    algo_id,
                    review_meta.get("verdict"),
                    review_meta.get("correct_count"),
                    len(target_bboxes),
                )
            elif llm_review_enabled():
                logger.warning(
                    "大模型复核跳过 task_id=%s algorithm=%s reason=detect_failed error=%s",
                    task_id,
                    algo_id,
                    body.get("error") or body.get("message"),
                )
                hits = []

            # 复核开启时：无复核结论或复核未确认正报，禁止入库（防多进程旧代码绕过）
            if llm_review_enabled() and body.get("success"):
                if not review_meta or review_meta.get("error"):
                    if hits:
                        logger.warning(
                            "复核未执行或失败，拒绝入库 task_id=%s algorithm=%s",
                            task_id,
                            algo_id,
                        )
                    hits = []
                elif int(review_meta.get("correct_count") or 0) <= 0:
                    hits = []

            if not hits:
                logger.info(
                    "大模型检测无有效检测框 task_id=%s algorithm=%s has_violation=%s "
                    "message=%s review=%s",
                    task_id,
                    algo_id,
                    body.get("has_violation"),
                    body.get("message") or body.get("error") or body.get("llm_analysis"),
                    review_meta.get("verdict") or "",
                )
                return {
                    "task_id": task_id,
                    "equipment_id": equipment_id,
                    "algorithm_id": algo_id,
                    "algorithm_name": algo_name,
                    "mode": "llm_detect",
                    "llm_kind": kind,
                    "has_violation": False,
                    "video_url": video_url,
                    "llm_review": review_meta or None,
                }, []

            best = max(hits, key=lambda h: float(h.get("confidence") or 0))
            if video_time_sec is not None:
                best["video_time_sec"] = round(video_time_sec, 3)
                ctx["alert_video_time_sec"] = video_time_sec
            conf = float(best.get("confidence") or threshold)
            detail = str(best.get("description") or body.get("llm_analysis") or "").strip()
            review_note = str(review_meta.get("llm_analysis") or "").strip()
            if review_note:
                detail = f"{detail}\n复核：{review_note}" if detail else f"复核：{review_note}"
            pseudo_dt = 1004 if kind == "play_phone" else None

            ev = self._event_svc.create(
                kind="video",
                title=_alert_event_title(algo_name),
                source_name=equip_name,
                work_id=str(work.get("work_id") or ""),
                work_name=str(work.get("name") or ""),
                region_id=region_id,
                region_name=region_name,
                equipment_id=equipment_id,
                algorithm_name=algo_name,
                rule_name=rule_name,
                status="pending",
                value_num=conf,
                threshold_text=_threshold_text(params, algo_id),
                snapshot_gradient=_event_gradient("video"),
                occurred_at=_utc_now(),
                reported_at=_utc_now(),
                resolution_detail=detail[:500] if detail else None,
                detection_json=_detection_json_from_llm_hit(
                    best,
                    detecttype=pseudo_dt,
                    video_duration_sec=video_duration_sec,
                    source_width=source_width,
                    source_height=source_height,
                    bbox_reference_width=int(body.get("image_width") or source_width),
                    bbox_reference_height=int(body.get("image_height") or source_height),
                ),
            )
            ev = self._finalize_video_event(
                ev, ctx, detecttype=pseudo_dt, params=params, llm_hit=best,
            )
            created: list[dict[str, Any]] = []
            if ev:
                logger.info(
                    "大模型检测告警入库 task_id=%s event_id=%s confidence=%.3f",
                    task_id,
                    ev.get("event_id"),
                    conf,
                )
                created.append(ev)
            else:
                logger.warning("大模型检测取证未对齐，已丢弃 task_id=%s", task_id)

            return {
                "task_id": task_id,
                "equipment_id": equipment_id,
                "algorithm_id": algo_id,
                "algorithm_name": algo_name,
                "mode": "llm_detect",
                "llm_kind": kind,
                "has_violation": True,
                "video_url": video_url,
                "llm_analysis": body.get("llm_analysis"),
                "llm_review": review_meta or None,
            }, created
        finally:
            if temp_jpg and os.path.isfile(temp_jpg):
                try:
                    os.unlink(temp_jpg)
                except OSError:
                    pass

    def _run_mock_video(
        self,
        *,
        task_id: str,
        work: dict[str, Any],
        equipment_id: str,
        equip_name: str,
        region_id: str,
        region_name: str,
        algo_id: str,
        algo_name: str,
        rule_name: str,
        params: dict[str, Any],
        vaio_available: bool,
        detecttype: int | None,
        evidence_ctx: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        mock = self._algo_svc.mock_invoke(algo_id, {"equipment_id": equipment_id, "params": params})
        conf = float(mock.get("confidence") or 0.0)
        threshold = float(params.get("confidence", params.get("detection/person/threshold", 0.85)))
        detected = bool(mock.get("detected")) or conf >= threshold
        logger.info(
            "占位推理 task_id=%s algorithm=%s detected=%s confidence=%s threshold=%s",
            task_id,
            algo_id,
            detected,
            conf,
            threshold,
        )

        created: list[dict[str, Any]] = []
        if detected:
            ev = self._event_svc.create(
                kind="video",
                title=f"{algo_name}告警",
                source_name=equip_name,
                work_id=str(work.get("work_id") or ""),
                work_name=str(work.get("name") or ""),
                region_id=region_id,
                region_name=region_name,
                equipment_id=equipment_id,
                algorithm_name=algo_name,
                rule_name=rule_name,
                status="pending",
                value_num=conf if conf > 0 else threshold,
                threshold_text=_threshold_text(params, algo_id),
                snapshot_gradient=_event_gradient("video"),
                occurred_at=_utc_now(),
                reported_at=_utc_now(),
            )
            ev = self._finalize_video_event(
                ev, dict(evidence_ctx or {}), detecttype=detecttype, params=params,
            )
            if ev:
                logger.info("占位推理告警入库 task_id=%s event_id=%s", task_id, ev.get("event_id"))
                created.append(ev)
            else:
                logger.warning("占位推理取证未对齐，已丢弃 task_id=%s", task_id)
        else:
            logger.info(
                "占位推理未检出阳性，跳过事件入库 task_id=%s algorithm=%s",
                task_id,
                algo_id,
            )

        return {
            "task_id": task_id,
            "equipment_id": equipment_id,
            "algorithm_id": algo_id,
            "mode": "mock",
            "detecttype": detecttype,
            "vaio_available": vaio_available,
        }, created

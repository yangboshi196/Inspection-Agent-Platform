"""LlmEngine HTTP 同步检测：POST /api/detect（见 LlmEngine 管理平台 services/detect）。"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LLM_DETECT_API = os.environ.get(
    "SIA_LLM_DETECT_API",
    os.environ.get("SIA_LLM_RULE_API", "http://10.19.155.38:8848/api/process-rule")
    .replace("/api/process-rule", "/api/detect"),
).strip()

_LLM_CLIENT_ID = os.environ.get("SIA_LLM_CLIENT_ID", "sia-platform").strip()

_LLM_REVIEW_API = os.environ.get(
    "SIA_LLM_REVIEW_API",
    _LLM_DETECT_API.replace("/api/detect", "/api/review"),
).strip()


def llm_review_enabled() -> bool:
    v = os.environ.get("SIA_LLM_REVIEW_ENABLED", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def llm_review_api_url() -> str:
    return _LLM_REVIEW_API


_PHONE_CALL_PROMPT = (
    "【任务】仅检测「正在用手机打电话」的作业人员；宁可漏报，不可把正常办公误判为打电话。\n"
    "【阳性（必须同时满足）】\n"
    "1. 能清晰辨认手机机身（小矩形电子设备，非鼠标/笔/水杯）；\n"
    "2. 手机贴耳或距耳很近，且呈通话姿态（侧头贴耳、嘴部微张等）；\n"
    "3. 人员主体在画面中可辨认。\n"
    "【一律阴性（不得出框、has_violation=false）】\n"
    "手背/侧身背对镜头，看不清是否握手机；手扶头、托腮、揉眼、捂耳、打哈欠；"
    "手持水杯/笔/鼠标/文件夹；双手在键盘鼠标或桌面上办公；"
    "仅手臂抬起靠近头部但看不见手机；远距离小人看不清手部细节；"
    "描述中出现「疑似」「可能」「无法确认」「看不清手机」时一律阴性。\n"
    "【输出】违规时 violations 须含 bbox；无把握时 has_violation=false。"
)

_PLAY_PHONE_PROMPT = (
    "【任务】仅检测「低头玩手机」的作业人员；正常用电脑办公不算玩手机。\n"
    "【阳性（必须同时满足）】\n"
    "1. 单手握持手机机身（小矩形屏设备），另一手可扶手机或自然下垂；\n"
    "2. 低头/视线明显落在手机屏幕（非电脑显示器）；\n"
    "3. 能辨认人员与手机，非空椅子或杂物。\n"
    "【一律阴性（不得出框、has_violation=false）】\n"
    "面对或背对电脑显示器敲键盘、看大屏；阅读纸质文件；手在脸旁但看不清手机；"
    "手背对镜头无法确认手持物是手机；仅桌面有手机但人员未操作；"
    "托腮休息、打电话姿态；描述「疑似」「可能」「无法确认」时一律阴性。\n"
    "【输出】违规时 violations 须含 bbox；无把握时 has_violation=false。"
)

_REVIEW_PLAY_PHONE_PROMPT = (
    "【复核】审核 detect 给出的目标框是否为「低头玩手机」正报；**默认判误报**。\n"
    "【仅当正报 correct_report】框内能清晰看见手持的小屏手机机身，且视线/头部明显朝向手机屏幕。\n"
    "【必须判误报 false_alarm】\n"
    "框住整个人或大半身体而非手机；面对/背对电脑显示器敲键盘；正常办公坐姿；"
    "手在桌面或脸旁但看不清手机；背对镜头无法确认手持物；"
    "框内仅有人员无手机设备；描述含疑似/看不清/无法确认。\n"
    "办公桌上使用电脑 ≠ 玩手机。"
)

_REVIEW_PHONE_CALL_PROMPT = (
    "【复核】审核 detect 目标框是否为「打电话」正报；**默认判误报**。\n"
    "【仅当正报】框内可见手机机身且贴耳/近耳通话姿态。\n"
    "【必须误报】托腮、揉眼、手背对镜头、正常办公、框住整个人看不清手机、疑似/看不清。"
)

_MAX_LLM_VIOLATION_BOX_AREA_RATIO = 0.22

# algorithm_id -> 检测配置（巡检直连大模型，不经 VAIO）
_LLM_DIRECT_BY_ID: dict[str, dict[str, str]] = {
    "llm-phone-call": {
        "kind": "phone_call",
        "label": "打电话",
        "prompt": _PHONE_CALL_PROMPT,
    },
    "llm-play-phone": {
        "kind": "play_phone",
        "label": "玩手机",
        "prompt": _PLAY_PHONE_PROMPT,
    },
}

_NAME_TO_ID: dict[str, str] = {
    "大模型-打电话": "llm-phone-call",
    "大模型-玩手机": "llm-play-phone",
}

_PHONE_CALL_NEG_MARKERS = (
    "未打电话",
    "未通话",
    "不作违规",
    "不判违规",
    "无法确认",
    "看不清",
    "难以辨认",
    "疑似",
    "可能",
    "不确定",
    "阴性",
    "不符合",
    "不属于",
    "排除",
    "正常办公",
    "托腮",
    "揉眼",
    "捂耳",
    "键盘",
    "鼠标",
    "水杯",
    "背对",
    "侧身",
    "手背",
)

_PLAY_PHONE_NEG_MARKERS = (
    "未玩手机",
    "不作违规",
    "不判违规",
    "无法确认",
    "看不清",
    "难以辨认",
    "疑似",
    "可能",
    "不确定",
    "阴性",
    "不符合",
    "不属于",
    "排除",
    "正常办公",
    "使用电脑",
    "看显示器",
    "看屏幕办公",
    "敲键盘",
    "阅读",
    "托腮",
    "打电话",
)


def llm_detect_api_url() -> str:
    return _LLM_DETECT_API


def resolve_llm_direct_config(
    algorithm_id: str,
    algo_name: str = "",
    schema: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """若算法为 LlmEngine 直连检测，返回 {kind, label, prompt}。"""
    aid = (algorithm_id or "").strip()
    if aid in _LLM_DIRECT_BY_ID:
        return dict(_LLM_DIRECT_BY_ID[aid])

    name = (algo_name or "").strip()
    if name in _NAME_TO_ID:
        return dict(_LLM_DIRECT_BY_ID[_NAME_TO_ID[name]])

    meta = (schema or {}).get("meta") if isinstance(schema, dict) else None
    if isinstance(meta, dict) and meta.get("llm_detect"):
        kind = str(meta.get("kind") or "").strip()
        if kind == "phone_call":
            return dict(_LLM_DIRECT_BY_ID["llm-phone-call"])
        if kind == "play_phone":
            return dict(_LLM_DIRECT_BY_ID["llm-play-phone"])
        prompt = str(meta.get("prompt") or "").strip()
        if prompt:
            return {
                "kind": kind or "custom",
                "label": str(meta.get("label") or "违规"),
                "prompt": prompt,
            }

    if "大模型" in name and "打电话" in name:
        return dict(_LLM_DIRECT_BY_ID["llm-phone-call"])
    if "大模型" in name and ("玩手机" in name or "手机" in name):
        return dict(_LLM_DIRECT_BY_ID["llm-play-phone"])
    return None


def _read_image_bytes(
    image_path: str | None = None,
    image_bytes: bytes | None = None,
) -> bytes | None:
    raw: bytes | None = image_bytes
    if raw is None and image_path:
        try:
            raw = Path(image_path).read_bytes()
        except OSError as exc:
            logger.warning("读取图片失败 path=%s error=%s", image_path, exc)
            return None
    return raw if raw else None


def _image_payload(image_name: str, raw: bytes) -> dict[str, str]:
    b64 = base64.b64encode(raw).decode()
    return {
        "name": image_name,
        "url": f"data:image/jpeg;base64,{b64}",
    }


def _post_llm_json(
    api_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 120.0,
    log_label: str = "LlmEngine",
) -> dict[str, Any]:
    if not api_url:
        return {"success": False, "error": f"{log_label} API 未配置"}
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Client-Id": _LLM_CLIENT_ID,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("%s 请求失败 api=%s error=%s", log_label, api_url, exc)
        return {"success": False, "error": str(exc)}
    if not isinstance(body, dict):
        return {"success": False, "error": "响应非 JSON 对象"}
    return body


def bbox_to_xyxy_list(
    bbox: Any,
    *,
    ref_width: int,
    ref_height: int,
) -> list[float] | None:
    """将 detect/review 多种 bbox 格式统一为 [x1,y1,x2,y2] 像素坐标。"""
    w = max(1, int(ref_width))
    h = max(1, int(ref_height))
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
    return [
        max(0.0, min(x1, float(w))),
        max(0.0, min(y1, float(h))),
        max(0.0, min(x2, float(w))),
        max(0.0, min(y2, float(h))),
    ]


def review_prompt_for_kind(kind: str, detect_prompt: str = "") -> str:
    """复核阶段使用更严提示词；未知 kind 回退 detect prompt。"""
    if kind == "play_phone":
        return _REVIEW_PLAY_PHONE_PROMPT
    if kind == "phone_call":
        return _REVIEW_PHONE_CALL_PROMPT
    return (detect_prompt or "").strip() or _PLAY_PHONE_PROMPT


def bbox_area_ratio(
    bbox: Any,
    *,
    ref_width: int,
    ref_height: int,
) -> float | None:
    xyxy = bbox_to_xyxy_list(bbox, ref_width=ref_width, ref_height=ref_height)
    if not xyxy:
        return None
    w = max(1, int(ref_width))
    h = max(1, int(ref_height))
    area = max(0.0, (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]))
    return area / float(w * h)


def filter_hits_by_bbox_area(
    hits: list[dict[str, Any]],
    *,
    ref_width: int,
    ref_height: int,
    max_area_ratio: float = _MAX_LLM_VIOLATION_BOX_AREA_RATIO,
) -> list[dict[str, Any]]:
    """过滤覆盖面积过大的框（多为整个人误报，非手机区域）。"""
    out: list[dict[str, Any]] = []
    for hit in hits:
        ratio = bbox_area_ratio(
            hit.get("bbox"),
            ref_width=ref_width,
            ref_height=ref_height,
        )
        if ratio is not None and ratio > max_area_ratio:
            continue
        out.append(hit)
    return out


def detect_image(
    *,
    prompt: str,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    image_name: str = "frame.jpg",
    model_id: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """调用 POST /api/detect，返回原始 JSON 体。"""
    raw = _read_image_bytes(image_path, image_bytes)
    if not raw:
        return {"success": False, "error": "无图片数据"}
    payload: dict[str, Any] = {
        "prompt": prompt.strip(),
        "image": _image_payload(image_name, raw),
    }
    if model_id:
        payload["model_id"] = model_id
    return _post_llm_json(_LLM_DETECT_API, payload, timeout=timeout, log_label="LlmEngine detect")


def review_detection(
    *,
    prompt: str,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    image_name: str = "frame.jpg",
    target_bboxes: list[list[float]] | None = None,
    alarm_id: str | None = None,
    algorithm: str | None = None,
    model_id: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """调用 POST /api/review：对 detect 检出的框做二次复核（正报/误报）。"""
    raw = _read_image_bytes(image_path, image_bytes)
    if not raw:
        return {"success": False, "error": "无图片数据"}
    payload: dict[str, Any] = {
        "prompt": prompt.strip(),
        "image": _image_payload(image_name, raw),
    }
    if target_bboxes:
        payload["target_bboxes"] = target_bboxes
    if alarm_id:
        payload["alarm_id"] = alarm_id.strip()
    if algorithm:
        payload["algorithm"] = algorithm.strip()
    if model_id:
        payload["model_id"] = model_id
    logger.info(
        "LlmEngine review 请求 api=%s alarm_id=%s algorithm=%s bboxes=%d",
        _LLM_REVIEW_API,
        alarm_id or "",
        algorithm or "",
        len(target_bboxes or []),
    )
    return _post_llm_json(_LLM_REVIEW_API, payload, timeout=timeout, log_label="LlmEngine review")


def filter_hits_by_review(
    hits: list[dict[str, Any]],
    review_body: dict[str, Any],
    *,
    ref_width: int,
    ref_height: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """仅保留复核「正报」的 hit；返回 (hits, review_meta)。"""
    meta: dict[str, Any] = {
        "verdict": str(review_body.get("verdict") or ""),
        "has_false_alarm": bool(review_body.get("has_false_alarm")),
        "llm_analysis": str(review_body.get("llm_analysis") or "").strip(),
        "iou_threshold": review_body.get("iou_threshold"),
        "false_alarm_count": len(review_body.get("false_alarms") or []),
    }
    if not review_body.get("success"):
        meta["error"] = str(review_body.get("error") or review_body.get("message") or "复核失败")
        return [], meta

    correct = review_body.get("correct_detections") or []
    if str(review_body.get("verdict") or "") == "false_alarm" or not correct:
        meta["correct_count"] = 0
        return [], meta

    out: list[dict[str, Any]] = []
    for item in correct:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if idx < 1 or idx > len(hits):
            continue
        hit = dict(hits[idx - 1])
        matched = item.get("matched_bbox")
        if matched:
            hit["bbox"] = matched
            if item.get("iou") is not None:
                hit["review_iou"] = item.get("iou")
        desc = str(item.get("description") or "").strip()
        if desc:
            hit["description"] = desc
        hit["source"] = "llm_detect_reviewed"
        out.append(hit)

    meta["correct_count"] = len(out)
    return out, meta


def body_to_hits(
    body: dict[str, Any],
    *,
    kind: str,
    image_name_ms: int = 0,
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """将 /api/detect 响应转为与 VAIO LLM 回补一致的 hit 列表。"""
    if not body.get("success"):
        return []
    if not body.get("has_violation"):
        return []

    analysis = str(body.get("llm_analysis") or "").strip()
    if analysis and not _is_positive_hit(analysis, kind):
        return []

    hits: list[dict[str, Any]] = []
    violations = body.get("violations") or []
    if not isinstance(violations, list):
        violations = []

    for item in violations:
        if not isinstance(item, dict):
            continue
        if not item.get("bbox"):
            continue
        try:
            conf = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < threshold:
            continue
        desc = str(item.get("description") or analysis).strip()
        if not _is_positive_hit(desc, kind):
            continue
        hits.append(
            {
                "confidence": conf,
                "class_name": "person",
                "description": desc,
                "bbox": item.get("bbox"),
                "frame_ms": image_name_ms,
                "video_time_sec": round(image_name_ms / 1000.0, 3) if image_name_ms else None,
                "source": "llm_detect_http",
                "llm_kind": kind,
            }
        )

    return hits


def body_to_review_candidates(
    body: dict[str, Any],
    *,
    kind: str,
    image_name_ms: int = 0,
    threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """从 detect 响应提取可送复核的候选框（仅要求 bbox，不做关键词过滤）。"""
    if not body.get("success") or not body.get("has_violation"):
        return []
    analysis = str(body.get("llm_analysis") or "").strip()
    violations = body.get("violations") or []
    if not isinstance(violations, list):
        violations = []
    out: list[dict[str, Any]] = []
    for item in violations:
        if not isinstance(item, dict) or not item.get("bbox"):
            continue
        try:
            conf = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < threshold:
            continue
        desc = str(item.get("description") or analysis).strip()
        out.append(
            {
                "confidence": conf,
                "class_name": "person",
                "description": desc,
                "bbox": item.get("bbox"),
                "frame_ms": image_name_ms,
                "video_time_sec": round(image_name_ms / 1000.0, 3) if image_name_ms else None,
                "source": "llm_detect_http",
                "llm_kind": kind,
            }
        )
    return out


def _is_positive_hit(description: str, kind: str) -> bool:
    text = (description or "").strip()
    if not text:
        return False
    if kind == "phone_call":
        if any(m in text for m in _PHONE_CALL_NEG_MARKERS):
            return False
        return any(
            k in text
            for k in (
                "正在打电话",
                "手机贴耳",
                "贴耳通话",
                "贴耳打电话",
                "手持手机通话",
                "耳边通话",
            )
        )
    if kind == "play_phone":
        if any(m in text for m in _PLAY_PHONE_NEG_MARKERS):
            return False
        return any(
            k in text
            for k in (
                "玩手机",
                "低头看手机",
                "注视手机屏幕",
                "手持手机",
                "看手机",
            )
        )
    return True

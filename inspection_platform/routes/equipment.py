"""设备 HTTP API。"""

from __future__ import annotations

import logging
import mimetypes
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Path, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from inspection_platform.equipment.service import EquipmentService

router = APIRouter(prefix="/api/equipment", tags=["equipment"])

logger = logging.getLogger(__name__)

EquipmentIdPath = Annotated[
    str,
    Path(min_length=1, max_length=128, description="设备主键 id。"),
]


@lru_cache
def get_equipment_service() -> EquipmentService:
    return EquipmentService()


class EquipmentCreateBody(BaseModel):
    id: str | None = Field(default=None, max_length=128, description="可选；冲突则 409。")
    kind: str = Field(..., description="camera | sensor")
    name: str = Field(..., min_length=1, max_length=512)
    region_id: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=4000)
    platform_name: str = Field(default="", max_length=512)
    platform_address: str = Field(default="", max_length=2048)
    thumbnail: str = Field(default="", max_length=2048)
    data_type: str = Field(default="", max_length=128)
    unit: str = Field(default="", max_length=64)
    online: bool = Field(default=True)


class EquipmentPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    kind: str | None = Field(default=None, description="camera | sensor")
    region_id: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    platform_name: str | None = Field(default=None, max_length=512)
    platform_address: str | None = Field(default=None, max_length=2048)
    thumbnail: str | None = Field(default=None, max_length=2048)
    data_type: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=64)
    online: bool | None = None


class EquipmentBatchImportRow(BaseModel):
    """批量导入单行；id 可选，缺省由服务端生成。"""

    id: str | None = Field(default=None, max_length=128)
    name: str = Field(..., min_length=1, max_length=512, description="设备名称")
    kind: str = Field(default="camera", description="camera | sensor")
    description: str = Field(default="", max_length=4000, description="地点、画面、业务等说明")
    region_id: str = Field(default="", max_length=128, description="所属区域 id")


class EquipmentBatchImportBody(BaseModel):
    items: list[EquipmentBatchImportRow] = Field(..., min_length=1, max_length=200)
    skip_existing: bool = Field(default=True, description="已存在 id 时跳过而非报错")


@router.get("/", summary="列出设备")
def list_equipment(
    kind: str | None = Query(default=None, description="camera | sensor"),
    region_id: str | None = Query(default=None, description="精确匹配单个区域 id"),
    region_ids: str | None = Query(
        default=None,
        description="逗号分隔的多个区域 id，用于区域树范围查询",
    ),
    online: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    scope_ids = [s.strip() for s in (region_ids or "").split(",") if s.strip()] or None
    items, total = get_equipment_service().list_equipment(
        kind=kind,
        region_id=region_id,
        region_ids=scope_ids,
        online=online,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/", status_code=201, summary="创建设备")
def create_equipment(body: EquipmentCreateBody) -> dict[str, Any]:
    svc = get_equipment_service()
    try:
        return svc.create(
            equipment_id=body.id,
            kind=body.kind,
            name=body.name,
            region_id=body.region_id,
            description=body.description,
            platform_name=body.platform_name,
            platform_address=body.platform_address,
            thumbnail=body.thumbnail,
            data_type=body.data_type,
            unit=body.unit,
            online=body.online,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.post("/import/batch", status_code=201, summary="批量导入设备")
def batch_import_equipment(body: EquipmentBatchImportBody) -> dict[str, Any]:
    """按模板字段批量创建设备；前端解析 CSV 后提交 JSON 数组。"""
    rows = [item.model_dump() for item in body.items]
    return get_equipment_service().batch_import(rows, skip_existing=body.skip_existing)


@router.get("/{equipment_id}", summary="获取设备")
def get_equipment(equipment_id: EquipmentIdPath) -> dict[str, Any]:
    row = get_equipment_service().get(equipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="equipment not found")
    return row


@router.patch("/{equipment_id}", summary="更新设备")
def patch_equipment(equipment_id: EquipmentIdPath, body: EquipmentPatchBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        row = get_equipment_service().get(equipment_id)
        if not row:
            raise HTTPException(status_code=404, detail="equipment not found")
        return row
    try:
        row = get_equipment_service().update(equipment_id, **payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="equipment not found")
    return row


@router.delete("/{equipment_id}", status_code=204, summary="删除设备")
def delete_equipment(equipment_id: EquipmentIdPath) -> Response:
    try:
        ok = get_equipment_service().delete(equipment_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="equipment not found")
    return Response(status_code=204)


@router.get("/{equipment_id}/readings", summary="传感器历史读数")
def list_sensor_readings(
    equipment_id: EquipmentIdPath,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items, total = get_equipment_service().list_readings(equipment_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _resolve_camera_rtsp(equipment_id: str, preview_rtsp: str | None = None) -> str:
    from urllib.parse import unquote

    from inspection_platform.equipment.stream_url import normalize_stream_url

    raw_preview = unquote((preview_rtsp or "").strip())
    if raw_preview:
        norm = normalize_stream_url(raw_preview)
        if norm:
            return norm
        if raw_preview.lower().startswith("rtsp://"):
            return raw_preview

    svc = get_equipment_service()
    row = svc.get(equipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="equipment not found")
    if str(row.get("kind") or "") != "camera":
        raise HTTPException(status_code=400, detail="仅摄像头支持实时预览")
    stream = normalize_stream_url(str(row.get("platform_address") or ""))
    if not stream:
        raise HTTPException(status_code=404, detail="未配置 RTSP 流地址")
    return stream


def _stream_mode_from_query(stream: str, quality: str) -> str:
    mode = (stream or "main").strip().lower()
    if mode in ("auto", "sub"):
        mode = "main"
    if mode != "main":
        mode = "main"
    return mode


def _quality_from_query(quality: str) -> str:
    q = (quality or "hd").strip().lower()
    if q in ("preview", "sd"):
        q = "hd"
    if q != "hd":
        q = "hd"
    return q


def _prepare_media_bridge(
    equipment_id: str,
    *,
    preview_rtsp: str | None,
    stream: str,
    quality: str,
    register_go2rtc: bool = True,
    wait_timeout: float = 15.0,
    max_attempts: int = 3,
) -> tuple[Any, str, str, str]:
    from inspection_platform.media.service import get_media_service

    rtsp_url = _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)
    media = get_media_service()
    if media.backend() != "go2rtc":
        return None, rtsp_url, stream, quality
    stream_mode = _stream_mode_from_query(stream, quality)
    q = _quality_from_query(quality)
    if register_go2rtc:
        try:
            media.ensure_stream(
                equipment_id,
                rtsp_url,
                stream_mode=stream_mode,
                quality=q,
                wait_timeout=wait_timeout,
                max_attempts=max_attempts,
            )
        except ValueError:
            pass
    return media, rtsp_url, stream_mode, q


@router.get("/{equipment_id}/live/play", summary="直播播放信息（多协议 URL）")
def live_play_info(
    equipment_id: EquipmentIdPath,
    stream: str = Query(default="main", description="auto | main | sub"),
    quality: str = Query(default="hd", description="preview | hd"),
    preview_rtsp: str | None = Query(default=None),
) -> dict[str, Any]:
    from inspection_platform.media.service import get_media_service

    _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)
    media = get_media_service()
    stream_mode = _stream_mode_from_query(stream, quality)
    q = _quality_from_query(quality)
    urls = media.play_urls(equipment_id, stream_mode=stream_mode, quality=q)
    if media.backend() == "go2rtc":
        from inspection_platform.media.service import go2rtc_key_mode, stream_key

        rtsp_url = _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)
        media.prune_sub_stream(equipment_id)
        key = stream_key(equipment_id, go2rtc_key_mode(stream_mode, q))
        # 仅查询当前 go2rtc 状态；不在 play 接口同步注册拉流（避免弹窗预览挂起）
        urls["producer_ready"] = media._producer_ready(key)  # noqa: SLF001
        if not urls["producer_ready"]:
            urls["producer_hint"] = media.producer_hint(key, rtsp_url)
    if preview_rtsp:
        from urllib.parse import quote

        pq = f"preview_rtsp={quote(preview_rtsp.strip(), safe='')}"
        for key in ("webrtc", "hls", "flv", "mp4", "mjpeg", "snapshot"):
            u = urls.get(key)
            if u and isinstance(u, str):
                urls[key] = f"{u}&{pq}"
    urls["rtsp_source"] = _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)
    return urls


@router.get("/{equipment_id}/live/snapshot", summary="摄像头 RTSP 单帧快照")
def live_snapshot(
    equipment_id: EquipmentIdPath,
    preview_rtsp: str | None = Query(default=None, description="未保存时预览用 RTSP（URL 编码）"),
    stream: str = Query(default="main", description="auto | main | sub"),
    quality: str = Query(default="hd", description="preview | hd"),
) -> Response:
    """go2rtc 抓帧；失败则 ffmpeg 直连。绝不返回空 body（避免 500）。"""
    from inspection_platform.equipment.rtsp_live import grab_rtsp_snapshot
    from inspection_platform.media.service import get_media_service

    rtsp_url = _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)
    stream_mode = _stream_mode_from_query(stream, quality)
    q = _quality_from_query(quality)
    cam_stream = "main"
    media = get_media_service()
    data: bytes | None = None
    last_err = ""

    # 配置页未保存地址：优先 ffmpeg 直连验证（不等 go2rtc 长注册）
    if (preview_rtsp or "").strip():
        try:
            data = grab_rtsp_snapshot(rtsp_url, stream=cam_stream, timeout_sec=12)
        except ValueError as e:
            last_err = str(e)

    if not data and media.backend() == "go2rtc":
        try:
            data = media.grab_frame_jpeg(
                equipment_id,
                rtsp_url,
                stream_mode=stream_mode,
                quality=q,
                timeout=8.0,
                wait_timeout=4.0,
            )
        except ValueError as e:
            last_err = last_err or str(e)

    if not data:
        try:
            data = grab_rtsp_snapshot(rtsp_url, stream=cam_stream, timeout_sec=15)
        except ValueError as e:
            last_err = last_err or str(e)

    if not data:
        raise HTTPException(
            status_code=502,
            detail=last_err or "无法获取 RTSP 快照，请检查地址、账号密码与平台服务器到摄像机的网络",
        )
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{equipment_id}/live/flv", summary="摄像头 HTTP-FLV 直播流")
def live_flv(
    equipment_id: EquipmentIdPath,
    stream: str = Query(
        default="main",
        description="码流：auto 按环境默认 | main 主码流（高清）| sub 子码流（预览）",
    ),
    quality: str = Query(
        default="hd",
        description="转码档位：preview 低延迟预览 | hd 详情/全屏（更高码率）",
    ),
    preview_rtsp: str | None = Query(default=None, description="未保存时预览用 RTSP（URL 编码）"),
) -> StreamingResponse:
    """HTTP-FLV：经 go2rtc 内网 RTSP 转 H.264；H.265 摄像机请用 WebRTC / MSE。"""
    stream_q = _stream_mode_from_query(stream, quality)
    q = _quality_from_query(quality)
    profile = "hd"

    media, rtsp_url, stream_mode, q = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=stream_q,
        quality=q,
        register_go2rtc=True,
    )

    if media:
        try:
            body = media.iter_flv_from_go2rtc(
                equipment_id,
                rtsp_url,
                stream_mode=stream_mode,
                quality=q,
                profile=profile,
            )
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return StreamingResponse(
            body,
            media_type="video/x-flv",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    from inspection_platform.equipment.rtsp_flv import iter_flv_stream

    try:
        body_legacy = iter_flv_stream(rtsp_url, stream=stream_q, profile=profile)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return StreamingResponse(
        body_legacy,
        media_type="video/x-flv",
        headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
    )


@router.get("/{equipment_id}/live/mjpeg", summary="摄像头 RTSP MJPEG 实时流")
async def live_mjpeg(
    equipment_id: EquipmentIdPath,
    fps: int = Query(default=15, ge=1, le=25, description="预览帧率上限"),
    preview_rtsp: str | None = Query(default=None, description="未保存时预览用 RTSP（URL 编码）"),
    stream: str = Query(default="main", description="MJPEG 固定主码流；sub 会被忽略"),
    quality: str = Query(default="hd", description="MJPEG 固定 hd；preview/sd 会被忽略"),
) -> StreamingResponse:
    """MJPEG 仅主码流 1080p（/101）；禁止子码流 /102 与 go2rtc _sub。"""
    stream_q = (stream or "main").strip().lower()
    q = (quality or "hd").strip().lower()
    if stream_q == "sub":
        logger.info("MJPEG 忽略 stream=sub，强制主码流 equipment=%s", equipment_id)
    if q == "preview":
        logger.info("MJPEG 忽略 quality=preview，强制 hd equipment=%s", equipment_id)
    mjpeg_mode = "main"
    mjpeg_quality = "hd"
    rtsp_url = _resolve_camera_rtsp(equipment_id, preview_rtsp=preview_rtsp)

    from inspection_platform.equipment.rtsp_live import MJPEG_BOUNDARY, iter_mjpeg_multipart, pick_stream_url

    def legacy_mjpeg() -> StreamingResponse:
        main_rtsp = pick_stream_url(rtsp_url, stream="main")
        try:
            body_legacy = iter_mjpeg_multipart(main_rtsp, fps=fps)
        except ValueError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return StreamingResponse(
            body_legacy,
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    # 未保存预览地址：直接 ffmpeg（不等 go2rtc）
    if (preview_rtsp or "").strip():
        return legacy_mjpeg()

    media, rtsp_url, _stream_mode, _q = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=mjpeg_mode,
        quality=mjpeg_quality,
        register_go2rtc=True,
        wait_timeout=3.0,
        max_attempts=2,
    )
    if media:
        from inspection_platform.media.service import stream_key

        media.prune_sub_stream(equipment_id)
        key = stream_key(equipment_id, "main")
        if media._producer_ready(key):  # noqa: SLF001
            upstream = media.go2rtc_upstream(
                equipment_id,
                "mjpeg",
                {"fps": str(fps)},
                stream_mode=mjpeg_mode,
                quality=mjpeg_quality,
            )

            async def body() -> Any:
                async for chunk in media.proxy_stream(upstream):
                    yield chunk

            return StreamingResponse(
                body(),
                media_type="multipart/x-mixed-replace; boundary=frame",
                headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
            )
        logger.warning(
            "go2rtc MJPEG 回退直连 RTSP equipment=%s hint=%s",
            equipment_id,
            media.producer_hint(key, rtsp_url),
        )

    return legacy_mjpeg()


@router.get("/{equipment_id}/live/mp4", summary="摄像头 fMP4/MSE 直播流（go2rtc）")
async def live_mp4(
    equipment_id: EquipmentIdPath,
    stream: str = Query(default="main"),
    quality: str = Query(default="hd"),
    preview_rtsp: str | None = Query(default=None),
) -> StreamingResponse:
    media, _, stream_mode, q = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=stream,
        quality=quality,
    )
    if not media:
        raise HTTPException(status_code=503, detail="MP4 直播需启用 go2rtc 流媒体服务")
    upstream = media.go2rtc_upstream(
        equipment_id, "mp4", {}, stream_mode=stream_mode, quality=q,
    )

    async def body() -> Any:
        async for chunk in media.proxy_stream(upstream):
            yield chunk

    return StreamingResponse(
        body(),
        media_type="video/mp4",
        headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
    )


@router.get("/{equipment_id}/live/hls/{resource:path}", summary="HLS 代理（go2rtc）")
async def live_hls_proxy(
    equipment_id: EquipmentIdPath,
    resource: str,
    request: Request,
    stream: str = Query(default="main"),
    quality: str = Query(default="hd"),
    preview_rtsp: str | None = Query(default=None),
) -> StreamingResponse:
    media, _, stream_mode, q = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=stream,
        quality=quality,
    )
    if not media:
        raise HTTPException(status_code=503, detail="HLS 需启用 go2rtc")
    suffix = resource.rsplit(".", 1)[-1].lower() if "." in resource else "m3u8"
    if suffix not in ("m3u8", "ts", "mp4"):
        suffix = "m3u8"
    query = {k: v for k, v in request.query_params.items() if k not in ("stream", "quality", "preview_rtsp")}
    upstream = media.go2rtc_upstream(
        equipment_id, suffix, query, stream_mode=stream_mode, quality=q,
    )

    async def body() -> Any:
        async for chunk in media.proxy_stream(upstream):
            yield chunk

    media_type = "application/vnd.apple.mpegurl" if suffix == "m3u8" else "video/mp2t"
    return StreamingResponse(
        body(),
        media_type=media_type,
        headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
    )


@router.get("/{equipment_id}/live/webrtc/embed", summary="WebRTC/MSE 嵌入页")
def live_webrtc_embed(
    equipment_id: EquipmentIdPath,
    stream: str = Query(default="main"),
    quality: str = Query(default="hd"),
    preview_rtsp: str | None = Query(default=None),
) -> Response:
    """内嵌播放器：优先 go2rtc WebRTC，回退 fMP4/HLS。"""
    from inspection_platform.media.service import go2rtc_key_mode, stream_key

    media, _, stream_mode, q = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=stream,
        quality=quality,
    )
    if not media:
        raise HTTPException(status_code=503, detail="需启用 go2rtc")
    key = stream_key(equipment_id, go2rtc_key_mode(stream_mode, q))
    from urllib.parse import quote

    stream_html_src = (
        f"/api/media/go2rtc/stream.html?src={quote(key, safe='')}&mode=webrtc"
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>实时预览</title>
<style>html,body{{margin:0;height:100%;background:#0f172a}}iframe{{border:0;width:100%;height:100%}}</style>
</head><body>
<iframe src="{stream_html_src}" allow="autoplay; fullscreen; microphone; camera"></iframe>
</body></html>"""
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/{equipment_id}/live/record", summary="从流媒体旁路录制 MP4")
def live_record_mp4(
    equipment_id: EquipmentIdPath,
    duration_sec: float = Query(default=30.0, ge=1.0, le=600.0),
    stream: str = Query(default="main"),
    preview_rtsp: str | None = Query(default=None),
) -> dict[str, Any]:
    from pathlib import Path
    from tempfile import mkstemp

    media, _ = _prepare_media_bridge(
        equipment_id,
        preview_rtsp=preview_rtsp,
        stream=stream,
        quality="hd",
    )
    if not media:
        raise HTTPException(status_code=503, detail="录像需启用 go2rtc")
    fd, tmp = mkstemp(suffix=".mp4", prefix="sia-record-")
    import os

    os.close(fd)
    dest = Path(tmp)
    try:
        media.record_mp4(equipment_id, dest, duration_sec=duration_sec, stream_mode=stream)
        data = dest.read_bytes()
    finally:
        dest.unlink(missing_ok=True)
    from inspection_platform.equipment.service import EquipmentService

    updated = EquipmentService().save_simulate_video(
        equipment_id,
        filename=f"record_{equipment_id}.mp4",
        content=data,
    )
    return {
        "ok": True,
        "path": updated.get("simulate_video_relpath"),
        "bytes": len(data),
        "duration_sec": duration_sec,
    }


@router.post("/{equipment_id}/simulate-video", summary="上传摄像头模拟适配视频")
async def upload_simulate_video(
    equipment_id: EquipmentIdPath,
    file: UploadFile = File(..., description="模拟视频文件（mp4/webm/mov 等）"),
) -> dict[str, Any]:
    raw = await file.read()
    svc = get_equipment_service()
    try:
        return svc.save_simulate_video(
            equipment_id,
            filename=file.filename or "simulate.mp4",
            content=raw,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.get("/{equipment_id}/simulate-video", summary="获取摄像头模拟适配视频")
def get_simulate_video(equipment_id: EquipmentIdPath) -> FileResponse:
    path = get_equipment_service().resolve_simulate_video_path(equipment_id)
    if not path:
        raise HTTPException(status_code=404, detail="simulate video not found")
    media = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return FileResponse(path, media_type=media, filename=path.name)


@router.delete("/{equipment_id}/simulate-video", status_code=204, summary="删除模拟适配视频")
def delete_simulate_video(equipment_id: EquipmentIdPath) -> Response:
    svc = get_equipment_service()
    try:
        row = svc.clear_simulate_video(equipment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="equipment not found")
    return Response(status_code=204)


@router.post("/seed/builtin", summary="导入内置演示设备")
def seed_builtin_equipment(replace_all: bool = Query(default=False)) -> dict[str, Any]:
    try:
        n = get_equipment_service().seed_builtin(replace_all=replace_all)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"inserted": n}

"""巡检事件 HTTP API。"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from inspection_platform.inspection_event.service import InspectionEventService

router = APIRouter(prefix="/api/inspection-events", tags=["inspection-events"])

EventIdPath = Annotated[
    str,
    Path(min_length=1, max_length=128, description="巡检事件主键 event_id。"),
]


@lru_cache
def get_inspection_event_service() -> InspectionEventService:
    return InspectionEventService()


class InspectionEventPatchBody(BaseModel):
    status: str | None = Field(
        default=None,
        description="pending | processing | resolved | ignored",
    )
    handler: str | None = Field(default=None, max_length=128)
    handled_at: str | None = Field(default=None, max_length=64)
    resolution_outcome: str | None = Field(default=None, max_length=256)
    resolution_detail: str | None = Field(default=None, max_length=4000)


class CreateInspectionEventBody(BaseModel):
    event_id: str | None = Field(default=None, max_length=128, description="可选；已存在则 409。")
    kind: str = Field(..., min_length=1, max_length=16, description="video | sensor")
    title: str = Field(..., min_length=1, max_length=500)
    source_name: str = Field(default="", max_length=256)
    work_id: str = Field(default="", max_length=128)
    work_name: str = Field(default="", max_length=500)
    region_id: str = Field(default="", max_length=200)
    region_name: str = Field(default="", max_length=512)
    equipment_id: str = Field(default="", max_length=128)
    algorithm_name: str = Field(default="", max_length=256)
    rule_name: str = Field(default="", max_length=256)
    status: str = Field(default="pending", max_length=32)
    value_num: float | None = Field(default=None)
    threshold_text: str = Field(default="", max_length=256)
    snapshot_gradient: str = Field(default="", max_length=512)
    occurred_at: str | None = Field(default=None, max_length=64)
    reported_at: str = Field(default="", max_length=64)
    handler: str = Field(default="", max_length=128)
    handled_at: str = Field(default="", max_length=64)
    resolution_outcome: str = Field(default="", max_length=256)
    resolution_detail: str = Field(default="", max_length=4000)


@router.post("/", summary="创建巡检事件", status_code=201)
def create_inspection_event(body: CreateInspectionEventBody) -> dict[str, Any]:
    svc = get_inspection_event_service()
    try:
        return svc.create(
            event_id=body.event_id,
            kind=body.kind,
            title=body.title,
            source_name=body.source_name,
            work_id=body.work_id,
            work_name=body.work_name,
            region_id=body.region_id,
            region_name=body.region_name,
            equipment_id=body.equipment_id,
            algorithm_name=body.algorithm_name,
            rule_name=body.rule_name,
            status=body.status,
            value_num=body.value_num,
            threshold_text=body.threshold_text,
            snapshot_gradient=body.snapshot_gradient,
            occurred_at=body.occurred_at,
            reported_at=body.reported_at,
            handler=body.handler,
            handled_at=body.handled_at,
            resolution_outcome=body.resolution_outcome,
            resolution_detail=body.resolution_detail,
        )
    except ValueError as e:
        msg = str(e)
        code = 409 if "已存在" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e


@router.get("/", summary="列出巡检事件")
def list_inspection_events(
    kind: str | None = Query(default=None, description="video | sensor"),
    status: str | None = Query(default=None),
    work_id: str | None = Query(default=None),
    region_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items, total = get_inspection_event_service().list_events(
        kind=kind,
        status=status,
        work_id=work_id,
        region_id=region_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/stats", summary="看板统计与趋势")
def inspection_dashboard_stats(
    trend_days: int = Query(default=7, ge=7, le=30, description="趋势统计天数"),
    trend_group_by: str = Query(
        default="event_type",
        description="分组维度：event_type / work / region / kind",
    ),
    trend_status: str | None = Query(default=None, description="事件状态：pending / processing / resolved / all"),
    trend_kind: str | None = Query(default=None, description="业务类型：video / sensor / all"),
    trend_region_id: str | None = Query(default=None, description="区域 ID，空为全部"),
    trend_date: str | None = Query(
        default=None,
        description="指定日期 YYYY-MM-DD；传入后按小时统计当日并返回事件明细",
    ),
    weekly_work_id: str | None = Query(default=None, description="巡检业务 work_id，空为全部"),
    weekly_risk_type: str | None = Query(default=None, description="风险类型（事件标题），空为全部"),
) -> dict[str, Any]:
    return get_inspection_event_service().dashboard_stats(
        trend_days=trend_days,
        trend_group_by=trend_group_by,
        trend_status=trend_status,
        trend_kind=trend_kind,
        trend_region_id=trend_region_id,
        trend_date=trend_date,
        weekly_work_id=weekly_work_id,
        weekly_risk_type=weekly_risk_type,
    )


@router.get("/runtime/works", summary="巡检业务运行态")
def inspection_work_runtime() -> dict[str, Any]:
    items = get_inspection_event_service().list_work_runtime()
    return {"items": items, "total": len(items)}


@router.post("/sync-media", summary="同步视频事件 RTSP 取证抓拍")
def sync_inspection_event_media(
    limit: int = Query(default=80, ge=1, le=500, description="扫描最近事件条数"),
) -> dict[str, Any]:
    return get_inspection_event_service().sync_video_event_media(limit=limit)


@router.get("/{event_id}", summary="获取单条巡检事件")
def get_inspection_event(event_id: EventIdPath) -> dict[str, Any]:
    row = get_inspection_event_service().get(event_id)
    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    return row


@router.patch("/{event_id}", summary="更新巡检事件状态")
def patch_inspection_event(event_id: EventIdPath, body: InspectionEventPatchBody) -> dict[str, Any]:
    svc = get_inspection_event_service()
    try:
        row = svc.update(
            event_id,
            status=body.status,
            handler=body.handler,
            handled_at=body.handled_at,
            resolution_outcome=body.resolution_outcome,
            resolution_detail=body.resolution_detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    return row


@router.post("/sync-detection-boxes", summary="补全事件检测框")
def sync_inspection_detection_boxes(
    limit: int = Query(default=80, ge=1, le=300, description="扫描最近事件条数"),
) -> dict[str, Any]:
    return get_inspection_event_service().sync_detection_boxes(limit=limit)


@router.post("/clear", summary="清空全部巡检事件")
def clear_inspection_events() -> dict[str, Any]:
    deleted = get_inspection_event_service().clear_all()
    return {"deleted": deleted}


@router.post("/seed/builtin", summary="导入内置演示事件")
def seed_builtin_events() -> dict[str, Any]:
    n = get_inspection_event_service().seed_builtin()
    return {"inserted": n}


@router.delete(
    "/{event_id}",
    status_code=204,
    response_class=Response,
    summary="删除巡检事件",
)
def delete_inspection_event(event_id: EventIdPath) -> Response:
    ok = get_inspection_event_service().delete(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="event not found")
    return Response(status_code=204)

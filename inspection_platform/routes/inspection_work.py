"""巡检业务 HTTP API 与生成编排。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from inspection_platform.deps import get_model_manager, get_specification_service
from inspection_platform.inspection_work.matcher import generate_inspection_works
from inspection_platform.inspection_work.service import InspectionWorkService
from inspection_platform.inspection_work.validation import validate_work_payload
from inspection_platform.inspection_work.tracking_times import validate_schedule_fields

router = APIRouter(prefix="/api/inspection-work", tags=["inspection-work"])
logger = logging.getLogger(__name__)

WorkIdPath = Annotated[
    str,
    Path(min_length=1, max_length=128, description="巡检业务主键 work_id。"),
]


@lru_cache
def get_inspection_work_service() -> InspectionWorkService:
    return InspectionWorkService()


class GenerateInspectionWorkBody(BaseModel):
    topic: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="用户巡检诉求；用于向量检索知识库规范并辅助 LLM 编组。",
    )
    region_id: str | None = Field(
        default=None,
        max_length=200,
        description="可选；限定设备范围到该区域。不传则使用全平台设备。",
    )
    max_works: int = Field(default=1, ge=1, le=1, description="每次固定生成 1 条巡检业务；Top-4 规范共同服务于该业务。")
    model_name: str | None = Field(default=None, description="聊天模型名；不传用默认。")
    persist: bool = Field(
        default=False,
        description="已停用；为 true 时返回 400，须人工确认后通过 POST / 手动入库。",
    )
    algorithm_limit: int = Field(
        default=40,
        ge=16,
        le=80,
        description="参与匹配的算法目录最大条数（越小越快、越不易超时）。",
    )
    rule_desc_max_chars: int = Field(
        default=400,
        ge=80,
        le=4000,
        description="送入 LLM 的规则 desc 最大字符数。",
    )
    rule_requirements_max_chars: int = Field(
        default=1200,
        ge=200,
        le=8000,
        description="送入 LLM 的规则 requirements 最大字符数。",
    )
    algorithm_desc_max_chars: int = Field(
        default=400,
        ge=80,
        le=800,
        description="送入 LLM 的算法说明最大字符数。",
    )


class CreateInspectionWorkBody(BaseModel):
    work_id: str | None = Field(default=None, max_length=128, description="可选；已存在则 409。")
    region_id: str | None = Field(
        default=None,
        max_length=200,
        description="主区域；未传 region_ids 时由 equipment_set 推导。",
    )
    region_ids: list[str] | None = Field(
        default=None,
        description="业务作用区域（可多选）；传入时优先于 equipment_set 推导。",
    )
    name: str = Field(..., min_length=1, max_length=500)
    desc: str = Field(default="", max_length=8000)
    rule_set: list[dict[str, Any]] = Field(default_factory=list)
    algorithm_set: list[dict[str, Any]] = Field(default_factory=list)
    equipment_set: list[dict[str, Any]] = Field(default_factory=list)
    equipment_algo_params: dict[str, Any] = Field(default_factory=dict)
    schedule_mode: str = Field(default="manual", max_length=32)
    schedule_interval: str | None = Field(default=None, max_length=64)
    schedule_times: str | None = Field(default=None, max_length=256)
    source: str = Field(default="manual", max_length=16)
    work_status: str = Field(default="online", max_length=16)


class PatchInspectionWorkBody(BaseModel):
    region_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="主区域；未传 region_ids 时由 equipment_set 推导。",
    )
    region_ids: list[str] | None = Field(
        default=None,
        description="业务作用区域（可多选）；传入时优先于 equipment_set 推导。",
    )
    name: str | None = Field(default=None, min_length=1, max_length=500)
    desc: str | None = Field(default=None, max_length=8000)
    rule_set: list[dict[str, Any]] | None = None
    algorithm_set: list[dict[str, Any]] | None = None
    equipment_set: list[dict[str, Any]] | None = None
    equipment_algo_params: dict[str, Any] | None = None
    schedule_mode: str | None = Field(default=None, max_length=32)
    schedule_interval: str | None = Field(default=None, max_length=64)
    schedule_times: str | None = Field(default=None, max_length=256)
    source: str | None = Field(default=None, max_length=16)
    work_status: str | None = Field(default=None, max_length=16)


@router.post(
    "/",
    summary="手动创建巡检业务",
    status_code=201,
)
def create_inspection_work(body: CreateInspectionWorkBody) -> dict[str, Any]:
    rw = get_inspection_work_service()
    spec_svc = get_specification_service()
    try:
        region_ids, primary_region = validate_work_payload(
            rule_set=body.rule_set,
            algorithm_set=body.algorithm_set,
            equipment_set=body.equipment_set,
            spec_svc=spec_svc,
            work_svc=rw,
            require_online_rules=body.work_status == "online",
            explicit_region_ids=body.region_ids,
        )
        rule_set = body.rule_set
        algorithm_set = body.algorithm_set
        if body.work_status == "online":
            rule_set, algorithm_set = rw.refresh_work_snapshots(
                rule_set=rule_set,
                algorithm_set=algorithm_set,
                spec_svc=spec_svc,
            )
        if body.work_status not in ("online", "offline"):
            raise ValueError("work_status 须为 online 或 offline")
        validate_schedule_fields(body.schedule_mode, body.schedule_interval, body.schedule_times)
        return rw.create(
            work_id=body.work_id,
            region_id=primary_region,
            region_ids=region_ids,
            name=body.name,
            desc=body.desc,
            rule_set=rule_set,
            algorithm_set=algorithm_set,
            equipment_set=body.equipment_set,
            equipment_algo_params=body.equipment_algo_params,
            schedule_mode=body.schedule_mode,
            schedule_interval=body.schedule_interval,
            schedule_times=body.schedule_times,
            source=body.source,
            work_status=body.work_status,
        )
    except ValueError as e:
        msg = str(e)
        code = 409 if "已存在" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e


@router.patch(
    "/{work_id}",
    summary="部分更新巡检业务",
)
def patch_inspection_work(work_id: WorkIdPath, body: PatchInspectionWorkBody) -> dict[str, Any]:
    rw = get_inspection_work_service()
    spec_svc = get_specification_service()
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        row = rw.get(work_id)
        if not row:
            raise HTTPException(status_code=404, detail="work not found")
        return row
    merged = rw.get(work_id)
    if not merged:
        raise HTTPException(status_code=404, detail="work not found")
    rule_set = payload.get("rule_set", merged.get("rule_set") or [])
    algorithm_set = payload.get("algorithm_set", merged.get("algorithm_set") or [])
    equipment_set = payload.get("equipment_set", merged.get("equipment_set") or [])
    next_status = payload.get("work_status", merged.get("work_status") or "online")
    explicit_region_ids = payload.get("region_ids") if "region_ids" in payload else None
    try:
        region_ids, primary_region = validate_work_payload(
            rule_set=rule_set,
            algorithm_set=algorithm_set,
            equipment_set=equipment_set,
            spec_svc=spec_svc,
            work_svc=rw,
            require_online_rules=next_status == "online",
            explicit_region_ids=explicit_region_ids if explicit_region_ids else None,
        )
        payload["region_ids"] = region_ids
        payload["region_id"] = primary_region
        if next_status == "online":
            rule_set, algorithm_set = rw.refresh_work_snapshots(
                rule_set=rule_set,
                algorithm_set=algorithm_set,
                spec_svc=spec_svc,
            )
            payload["rule_set"] = rule_set
            payload["algorithm_set"] = algorithm_set
        if payload.get("work_status") is not None and payload["work_status"] not in (
            "online",
            "offline",
        ):
            raise ValueError("work_status 须为 online 或 offline")
        next_mode = str(payload.get("schedule_mode", merged.get("schedule_mode") or "manual"))
        next_interval = payload.get("schedule_interval", merged.get("schedule_interval"))
        next_times = payload.get("schedule_times", merged.get("schedule_times"))
        if {"schedule_mode", "schedule_interval", "schedule_times"} & payload.keys():
            validate_schedule_fields(next_mode, next_interval, next_times)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    row = rw.update(work_id, **payload)
    if not row:
        raise HTTPException(status_code=404, detail="work not found")
    if {"schedule_mode", "schedule_interval", "schedule_times"} & payload.keys():
        from inspection_platform.inspection_work.tracking import WorkTrackingService

        WorkTrackingService().sync_schedule_config(work_id)
    return row


@router.post(
    "/generate",
    summary="智能匹配规则与算法并生成巡检业务",
    description=(
        "按用户描述向量检索已发布规范（动态 K，min_score + gap），"
        "合并意图识别与规范绑定目录后综合生成一条巡检业务；"
        "实体字段含 name、region_id、region_ids、desc、"
        "rule_set（含 rule_id）、algorithm_set（含 algorithm_id）、equipment_set。"
        "生成结果须人工确认后通过 POST / 手动入库。"
    ),
)
def generate_inspection_work(body: GenerateInspectionWorkBody) -> dict[str, Any]:
    if body.persist:
        raise HTTPException(
            status_code=400,
            detail="persist 已停用，请人工确认生成结果后通过 POST /api/inspection-work/ 手动入库",
        )
    mm = get_model_manager()
    spec_svc = get_specification_service()
    try:
        result = generate_inspection_works(
            spec_svc=spec_svc,
            mm=mm,
            region_id=body.region_id,
            model_name=body.model_name,
            max_works=body.max_works,
            topic=body.topic,
            algorithm_limit=body.algorithm_limit,
            rule_desc_max_chars=body.rule_desc_max_chars,
            rule_requirements_max_chars=body.rule_requirements_max_chars,
            algorithm_desc_max_chars=body.algorithm_desc_max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {type(e).__name__}: {e}") from e

    drafts = result.get("works") or []
    trace = result.get("retrieval_trace") or {}
    works_out: list[dict[str, Any]] = []
    for w in drafts:
        row = dict(w)
        row["ai_generation_trace"] = trace
        works_out.append(row)
    return {
        "count": len(works_out),
        "works": works_out,
        "retrieval_trace": trace,
    }


@router.get(
    "/",
    summary="列出巡检业务",
)
def list_inspection_works(
    region_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=200,
        description="区域 ID；返回关联该区域（含多区域）的巡检业务。",
    ),
    equipment_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
        description="设备 ID；返回绑定该设备的巡检业务。",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rw = get_inspection_work_service()
    if equipment_id:
        items, total = rw.list_by_equipment(equipment_id, limit=limit, offset=offset)
    elif region_id:
        items, total = rw.list_by_region(region_id, limit=limit, offset=offset)
    else:
        items, total = rw.list_all(limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/tracking/summary", summary="业务追踪各状态数量")
def inspection_work_tracking_summary() -> dict[str, Any]:
    from inspection_platform.inspection_work.tracking import WorkTrackingService

    return WorkTrackingService().summary()


@router.get("/tracking", summary="业务追踪列表（仅已发布）")
def list_inspection_work_tracking(
    status: str | None = Query(
        default=None,
        description="waiting / running / completed；不传则返回全部已发布",
    ),
) -> dict[str, Any]:
    from inspection_platform.inspection_work.tracking import WorkTrackingService

    if status is not None and status.strip() not in ("waiting", "running", "completed"):
        raise HTTPException(status_code=400, detail="status 须为 waiting / running / completed")
    items = WorkTrackingService().list_published(
        queue_status=status.strip() if status else None,
    )
    return {"items": items, "total": len(items)}


@router.get("/tracking/{work_id}", summary="单条业务追踪状态")
def get_inspection_work_tracking(work_id: WorkIdPath) -> dict[str, Any]:
    from inspection_platform.inspection_work.tracking import WorkTrackingService

    row = WorkTrackingService().get(work_id)
    if not row:
        return {"work_id": work_id, "published": False}
    return row


@router.post("/tracking/{work_id}/publish", summary="发布业务到追踪队列")
def publish_inspection_work_tracking(work_id: WorkIdPath) -> dict[str, Any]:
    from inspection_platform.inspection_work.tracking import WorkTrackingService

    try:
        return WorkTrackingService().publish(work_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/tracking/{work_id}/unpublish", summary="从业务追踪下架")
def unpublish_inspection_work_tracking(work_id: WorkIdPath) -> dict[str, Any]:
    from inspection_platform.inspection_work.tracking import WorkTrackingService

    try:
        return WorkTrackingService().unpublish(work_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/{work_id}",
    summary="获取单条巡检业务",
)
def get_inspection_work(work_id: WorkIdPath) -> dict[str, Any]:
    row = get_inspection_work_service().get(work_id)
    if not row:
        raise HTTPException(status_code=404, detail="work not found")
    return row


@router.post(
    "/{work_id}/run",
    summary="手动触发巡检业务",
    description="运行周期为 manual 时，按设备×算法调用 VAIO（或占位推理），结果写入巡检事件表。",
)
def run_inspection_work(work_id: WorkIdPath) -> dict[str, Any]:
    from inspection_platform.inspection_work.runner import InspectionWorkRunner

    logger.info("收到手动触发请求 work_id=%s", work_id)
    try:
        result = InspectionWorkRunner().run_manual(work_id)
        logger.info(
            "手动触发完成 work_id=%s events_created=%s task_count=%s warning_count=%s",
            work_id,
            result.get("events_created"),
            len(result.get("tasks") or []),
            len(result.get("warnings") or []),
        )
        return result
    except ValueError as e:
        logger.warning("手动触发拒绝 work_id=%s detail=%s", work_id, e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.error("手动触发失败 work_id=%s detail=%s", work_id, e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.delete(
    "/{work_id}",
    summary="删除巡检业务",
)
def delete_inspection_work(work_id: WorkIdPath) -> dict[str, Any]:
    ok = get_inspection_work_service().delete(work_id)
    if not ok:
        raise HTTPException(status_code=404, detail="work not found")
    return {"deleted": True, "work_id": work_id}


@router.post("/seed/builtin", summary="导入内置演示巡检业务")
def seed_builtin_inspection_work(replace_all: bool = Query(default=False)) -> dict[str, Any]:
    try:
        n = get_inspection_work_service().seed_builtin(replace_all=replace_all)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"inserted": n}

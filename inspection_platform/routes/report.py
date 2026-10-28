"""报告库 HTTP API。"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Path, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from inspection_platform.report.service import ReportService

router = APIRouter(tags=["reports"])

TemplateIdPath = Annotated[str, Path(min_length=1, max_length=128)]
PlanIdPath = Annotated[str, Path(min_length=1, max_length=128)]
ReportIdPath = Annotated[str, Path(min_length=1, max_length=128)]


@lru_cache
def get_report_service() -> ReportService:
    return ReportService()


# --- templates ---


class ReportTemplateCreateBody(BaseModel):
    template_id: str | None = Field(default=None, max_length=128)
    name: str = Field(..., min_length=1, max_length=512)
    description: str = Field(default="", max_length=2000)
    filename: str = Field(default="", max_length=512)
    content: str = Field(default="", max_length=64000)
    storage_relpath: str = Field(default="", max_length=512)
    uploaded_at: str | None = Field(default=None, max_length=64)
    size_label: str = Field(default="", max_length=64)


class ReportTemplatePatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=2000)
    filename: str | None = Field(default=None, max_length=512)
    content: str | None = Field(default=None, max_length=64000)
    uploaded_at: str | None = Field(default=None, max_length=64)
    size_label: str | None = Field(default=None, max_length=64)


@router.get("/api/report-templates/", summary="列出报告模版")
def list_report_templates(
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items, total = get_report_service().list_templates(q=q, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/api/report-templates/", status_code=201, summary="创建报告模版")
def create_report_template(body: ReportTemplateCreateBody) -> dict[str, Any]:
    svc = get_report_service()
    try:
        return svc.create_template(
            template_id=body.template_id,
            name=body.name,
            description=body.description,
            filename=body.filename,
            content=body.content,
            storage_relpath=body.storage_relpath,
            uploaded_at=body.uploaded_at,
            size_label=body.size_label,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.post("/api/report-templates/upload", status_code=201, summary="上传文件并创建报告模版")
async def upload_report_template(
    file: UploadFile = File(..., description="报告模版文件（txt/md/doc/docx）"),
    name: str | None = Query(default=None, max_length=512),
    description: str | None = Query(default=None, max_length=2000),
) -> dict[str, Any]:
    raw = await file.read()
    svc = get_report_service()
    try:
        return svc.create_template_from_upload(
            file_content=raw,
            original_filename=file.filename or "template.txt",
            name=name,
            description=description or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/report-templates/dedupe", summary="合并正文相同的报告模版")
def dedupe_report_templates_api() -> dict[str, Any]:
    from inspection_platform.report.dedupe_templates import dedupe_report_templates

    # 允许管理端手动触发；进程内 dedupe 有缓存，此处强制重置后执行
    import inspection_platform.report.dedupe_templates as dedupe_mod

    dedupe_mod._DEDUPED = False
    stats = dedupe_report_templates()
    return {"ok": True, **stats}


@router.post("/api/report-templates/{template_id}", status_code=201, summary="创建报告模版（路径指定 template_id）")
def create_report_template_with_id(
    template_id: TemplateIdPath,
    body: ReportTemplateCreateBody,
) -> dict[str, Any]:
    """兼容误将 POST 发到 /{template_id} 的客户端（此前返回 405）。"""
    svc = get_report_service()
    existing = svc.resolve_template(template_id)
    if existing:
        raise HTTPException(status_code=409, detail="模版已存在")
    path_key = template_id.strip()
    use_id = path_key if path_key.startswith(("tpl-", "wrt-")) else None
    try:
        return svc.create_template(
            template_id=use_id,
            name=body.name or path_key,
            description=body.description,
            filename=body.filename,
            content=body.content,
            storage_relpath=body.storage_relpath,
            uploaded_at=body.uploaded_at,
            size_label=body.size_label,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.get("/api/report-templates/{template_id}", summary="获取报告模版")
def get_report_template(template_id: TemplateIdPath) -> dict[str, Any]:
    row = get_report_service().resolve_template(template_id)
    if not row:
        raise HTTPException(status_code=404, detail="template not found")
    return row


@router.patch("/api/report-templates/{template_id}", summary="更新报告模版")
def patch_report_template(template_id: TemplateIdPath, body: ReportTemplatePatchBody) -> dict[str, Any]:
    row = get_report_service().update_template(template_id, **body.model_dump(exclude_unset=True))
    if not row:
        raise HTTPException(status_code=404, detail="template not found")
    return row


@router.delete(
    "/api/report-templates/{template_id}",
    status_code=204,
    response_class=Response,
    summary="删除报告模版",
)
def delete_report_template(template_id: TemplateIdPath) -> Response:
    try:
        ok = get_report_service().delete_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="template not found")
    return Response(status_code=204)


# --- plans ---


class ReportPlanCreateBody(BaseModel):
    plan_id: str | None = Field(default=None, max_length=128)
    name: str = Field(..., min_length=1, max_length=512)
    enabled: bool = Field(default=True)
    frequency: str = Field(default="daily", description="daily | weekly | monthly")
    work_ids: list[str] = Field(default_factory=list)
    content_prompt: str = Field(default="", max_length=8000)
    template_id: str | None = Field(default=None, max_length=128)
    weekday: int | None = Field(default=None, ge=1, le=7)
    month_day: int | None = Field(default=None, ge=1, le=28)
    generate_time: str = Field(default="08:00", max_length=16)


class ReportPlanPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    enabled: bool | None = None
    frequency: str | None = Field(default=None, description="daily | weekly | monthly")
    work_ids: list[str] | None = None
    content_prompt: str | None = Field(default=None, max_length=8000)
    template_id: str | None = Field(default=None, max_length=128)
    weekday: int | None = Field(default=None, ge=1, le=7)
    month_day: int | None = Field(default=None, ge=1, le=28)
    generate_time: str | None = Field(default=None, max_length=16)


@router.get("/api/report-plans/", summary="列出报告生成计划")
def list_report_plans(
    frequency: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items, total = get_report_service().list_plans(
        frequency=frequency,
        enabled=enabled,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/api/report-plans/", status_code=201, summary="创建报告生成计划")
def create_report_plan(body: ReportPlanCreateBody) -> dict[str, Any]:
    svc = get_report_service()
    try:
        return svc.create_plan(
            plan_id=body.plan_id,
            name=body.name,
            enabled=body.enabled,
            frequency=body.frequency,
            work_ids=body.work_ids,
            content_prompt=body.content_prompt,
            template_id=body.template_id,
            weekday=body.weekday,
            month_day=body.month_day,
            generate_time=body.generate_time,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.get("/api/report-plans/{plan_id}", summary="获取报告生成计划")
def get_report_plan(plan_id: PlanIdPath) -> dict[str, Any]:
    row = get_report_service().get_plan(plan_id)
    if not row:
        raise HTTPException(status_code=404, detail="plan not found")
    return row


@router.patch("/api/report-plans/{plan_id}", summary="更新报告生成计划")
def patch_report_plan(plan_id: PlanIdPath, body: ReportPlanPatchBody) -> dict[str, Any]:
    svc = get_report_service()
    try:
        row = svc.update_plan(plan_id, **body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="plan not found")
    return row


@router.post("/api/report-plans/{plan_id}/toggle", summary="切换计划启用状态")
def toggle_report_plan(plan_id: PlanIdPath) -> dict[str, Any]:
    row = get_report_service().toggle_plan(plan_id)
    if not row:
        raise HTTPException(status_code=404, detail="plan not found")
    return row


@router.delete(
    "/api/report-plans/{plan_id}",
    status_code=204,
    response_class=Response,
    summary="删除报告生成计划",
)
def delete_report_plan(plan_id: PlanIdPath) -> Response:
    ok = get_report_service().delete_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="plan not found")
    return Response(status_code=204)


# --- inspection reports ---


class ReportSectionBody(BaseModel):
    id: str = Field(..., max_length=128)
    title: str = Field(..., max_length=256)
    body: str = Field(default="", max_length=16000)
    detail: str | None = Field(default=None, max_length=32000)


class InspectionReportCreateBody(BaseModel):
    report_id: str | None = Field(default=None, max_length=128)
    title: str = Field(..., min_length=1, max_length=512)
    period: str = Field(default="", max_length=128)
    frequency: str = Field(default="weekly", max_length=32)
    work_ids: list[str] = Field(default_factory=list)
    status: str = Field(default="draft", max_length=32)
    source: str = Field(default="manual", max_length=32)
    content_prompt: str = Field(default="", max_length=8000)
    plan_id: str | None = Field(default=None, max_length=128)
    plan_name: str | None = Field(default=None, max_length=512)
    template_id: str | None = Field(default=None, max_length=128)
    template_name: str | None = Field(default=None, max_length=512)
    summary: str = Field(default="", max_length=8000)
    sections: list[ReportSectionBody] = Field(default_factory=list)
    full_text: str = Field(default="", max_length=64000)


class InspectionReportPatchBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    period: str | None = Field(default=None, max_length=128)
    frequency: str | None = Field(default=None, max_length=32)
    work_ids: list[str] | None = None
    status: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default=None, max_length=32)
    content_prompt: str | None = Field(default=None, max_length=8000)
    plan_id: str | None = Field(default=None, max_length=128)
    plan_name: str | None = Field(default=None, max_length=512)
    template_id: str | None = Field(default=None, max_length=128)
    template_name: str | None = Field(default=None, max_length=512)
    summary: str | None = Field(default=None, max_length=8000)
    sections: list[ReportSectionBody] | None = None
    full_text: str | None = Field(default=None, max_length=64000)


@router.post("/api/report-plans/{plan_id}/generate", status_code=201, summary="按计划生成巡检报告")
def generate_report_from_plan(plan_id: PlanIdPath, source: str = Query(default="manual")) -> dict[str, Any]:
    svc = get_report_service()
    try:
        return svc.generate_from_plan(plan_id, source=source)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail="plan not found") from e
        raise HTTPException(status_code=400, detail=str(e)) from e


class AdhocReportGenerateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    work_ids: list[str] = Field(default_factory=list)
    content_prompt: str = Field(default="", max_length=8000)
    template_id: str | None = Field(default=None, max_length=128)


@router.post("/api/inspection-reports/generate-adhoc", status_code=201, summary="临时生成巡检报告")
def generate_adhoc_report(body: AdhocReportGenerateBody) -> dict[str, Any]:
    from inspection_platform.deps import get_model_manager
    from inspection_platform.document.region_meta import RegionMetaService
    from inspection_platform.report.generator import build_adhoc_report
    from inspection_platform.inspection_work.service import InspectionWorkService

    svc = get_report_service()
    template = svc.get_template(body.template_id) if body.template_id else None

    rw = InspectionWorkService()
    works_catalog, _ = rw.list_all(limit=500, offset=0)

    region_svc = RegionMetaService()
    regions = region_svc.list_regions()
    region_names = {str(r.get("id") or ""): str(r.get("name") or "") for r in regions}

    try:
        mm = get_model_manager()
    except Exception:
        mm = None

    draft = build_adhoc_report(
        name=body.name,
        work_ids=body.work_ids,
        content_prompt=body.content_prompt,
        template=template,
        works_catalog=works_catalog,
        region_names=region_names,
        model_manager=mm,
    )
    draft.pop("created_at", None)
    draft.pop("updated_at", None)
    return svc.create_report(**draft)


@router.get("/api/inspection-reports/", summary="列出巡检报告")
def list_inspection_reports(
    request: Request,
    status: str | None = Query(default=None),
    frequency: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    subscribed_only: bool = Query(default=False, description="用户看板：仅返回当前用户订阅业务相关报告"),
) -> dict[str, Any]:
    subscribed_work_ids: set[str] | None = None
    has_subscription: bool | None = None
    if subscribed_only:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未登录")
        from inspection_platform.report.push_subscription import ReportPushSubscriptionService

        work_ids = ReportPushSubscriptionService().get_work_ids_for_user(str(user.get("user_id") or ""))
        has_subscription = bool(work_ids)
        subscribed_work_ids = set(work_ids)

    items, total = get_report_service().list_reports(
        status=status,
        frequency=frequency,
        plan_id=plan_id,
        q=q,
        limit=limit,
        offset=offset,
        subscribed_work_ids=subscribed_work_ids,
    )
    out: dict[str, Any] = {"items": items, "total": total, "limit": limit, "offset": offset}
    if has_subscription is not None:
        out["has_subscription"] = has_subscription
    return out


@router.post("/api/inspection-reports/seed/builtin", summary="导入内置演示报告数据")
def seed_builtin_reports() -> dict[str, Any]:
    return get_report_service().seed_builtin()


@router.post("/api/inspection-reports/", status_code=201, summary="创建巡检报告")
def create_inspection_report(body: InspectionReportCreateBody) -> dict[str, Any]:
    svc = get_report_service()
    sections = [s.model_dump() for s in body.sections]
    try:
        return svc.create_report(
            report_id=body.report_id,
            title=body.title,
            period=body.period,
            frequency=body.frequency,
            work_ids=body.work_ids,
            status=body.status,
            source=body.source,
            content_prompt=body.content_prompt,
            plan_id=body.plan_id,
            plan_name=body.plan_name,
            template_id=body.template_id,
            template_name=body.template_name,
            summary=body.summary,
            sections=sections,
            full_text=body.full_text,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.get("/api/inspection-reports/{report_id}", summary="获取巡检报告")
def get_inspection_report(report_id: ReportIdPath) -> dict[str, Any]:
    row = get_report_service().get_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return row


@router.patch("/api/inspection-reports/{report_id}", summary="更新巡检报告")
def patch_inspection_report(report_id: ReportIdPath, body: InspectionReportPatchBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if "sections" in payload and payload["sections"] is not None:
        payload["sections"] = payload["sections"]
    row = get_report_service().update_report(report_id, **payload)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return row


@router.post("/api/inspection-reports/{report_id}/publish", summary="发布巡检报告")
def publish_inspection_report(report_id: ReportIdPath) -> dict[str, Any]:
    row = get_report_service().publish_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return row


@router.delete(
    "/api/inspection-reports/{report_id}",
    status_code=204,
    response_class=Response,
    summary="删除巡检报告",
)
def delete_inspection_report(report_id: ReportIdPath) -> Response:
    ok = get_report_service().delete_report(report_id)
    if not ok:
        raise HTTPException(status_code=404, detail="report not found")
    return Response(status_code=204)

"""巡检业务报告模版绑定 HTTP API。"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile
from pydantic import BaseModel, Field

from inspection_platform.report.work_template_binding import WorkReportTemplateBindingService

router = APIRouter(prefix="/api/work-report-template-bindings", tags=["work-report-template"])

WorkIdPath = Annotated[str, Path(min_length=1, max_length=128, description="巡检业务 work_id")]


class WorkReportTemplateEnabledBody(BaseModel):
    work_ids: list[str] = Field(..., min_length=1, description="巡检业务 work_id 列表")
    enabled: bool = Field(..., description="是否启用报告模版绑定")


class WorkReportTemplateBindBody(BaseModel):
    work_ids: list[str] = Field(..., min_length=1, description="巡检业务 work_id 列表")
    template_id: str = Field(..., min_length=1, max_length=128, description="report_template.template_id")
    enabled: bool = Field(default=True, description="绑定后是否启用")


class WorkReportTemplateSaveBody(BaseModel):
    template_id: str | None = Field(default=None, description="为空表示不自动生成报告")


@lru_cache
def get_binding_service() -> WorkReportTemplateBindingService:
    return WorkReportTemplateBindingService()


@router.get("/", summary="列出全部业务报告模版绑定")
def list_work_report_template_bindings() -> dict[str, Any]:
    items = get_binding_service().list_bindings()
    return {"items": items, "total": len(items)}


@router.post("/upload", summary="上传报告模版并绑定到一个或多个业务")
async def upload_work_report_template_binding(
    file: UploadFile = File(..., description="报告模版文件（txt/md/doc/docx）"),
    work_ids: str = Form(..., description='JSON 数组，如 ["iw-1","iw-2"]'),
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
) -> dict[str, Any]:
    try:
        ids = json.loads(work_ids)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="work_ids 须为 JSON 数组") from e
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="work_ids 须为 JSON 数组")
    raw = await file.read()
    try:
        items = get_binding_service().upload_and_bind(
            work_ids=[str(x) for x in ids],
            file_content=raw,
            original_filename=file.filename or "template.txt",
            name=name,
            description=description or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"items": items, "count": len(items)}


@router.put("/bind", summary="将已有报告模版绑定到一个或多个业务")
def bind_work_report_template(body: WorkReportTemplateBindBody) -> dict[str, Any]:
    try:
        items = get_binding_service().bind_template(
            work_ids=body.work_ids,
            template_id=body.template_id,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"items": items, "count": len(items)}


@router.put("/enabled", summary="批量设置业务是否启用报告模版绑定")
def set_work_report_template_binding_enabled(body: WorkReportTemplateEnabledBody) -> dict[str, Any]:
    try:
        items = get_binding_service().set_enabled(
            work_ids=body.work_ids,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"items": items, "count": len(items)}


@router.get("/{work_id}", summary="获取单条业务报告模版绑定")
def get_work_report_template_binding(work_id: WorkIdPath) -> dict[str, Any]:
    row = get_binding_service().get_binding(work_id)
    if not row:
        raise HTTPException(status_code=404, detail="该业务尚未绑定报告模版")
    return row


@router.put("/{work_id}", summary="保存单条业务报告模版绑定")
def save_work_report_template_binding(
    work_id: WorkIdPath,
    body: WorkReportTemplateSaveBody,
) -> dict[str, Any]:
    try:
        row = get_binding_service().save_binding(work_id=work_id, template_id=body.template_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if row:
        return row
    return {"work_id": work_id, "cleared": True}

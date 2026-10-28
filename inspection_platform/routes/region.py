"""region HTTP API（独立 SQLite，与 /api/document 无关）。"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from inspection_platform.document.region_meta import RegionMetaService
from inspection_platform.equipment.service import EquipmentService

router = APIRouter(prefix="/api/region", tags=["region"])

RegionMetaIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=256,
        description="区域元数据主键 id；在 region 专用 SQLite 中唯一，与 document.region_id 仅业务上可对应。",
    ),
]


@lru_cache
def get_region_meta_service() -> RegionMetaService:
    return RegionMetaService()


class RegionCreatePayload(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="新建区域的 id，须唯一；可与业务上的区域编码一致。",
    )
    name: str = Field(
        default="",
        max_length=512,
        description="区域展示名称；可为空字符串。",
    )
    desc: str = Field(
        default="",
        max_length=2048,
        description="区域说明、职责描述等；可为空。",
    )
    parent_id: str = Field(
        default="",
        max_length=256,
        description="上级区域 id；空表示顶级区域。",
    )
    sort_order: int = Field(
        default=0,
        description="同级排序，数值越小越靠前。",
    )


class RegionPatchPayload(BaseModel):
    name: str | None = Field(default=None, max_length=512, description="新展示名；不传不改。")
    desc: str | None = Field(default=None, max_length=2048, description="新说明；不传不改。")
    parent_id: str | None = Field(default=None, max_length=256, description="新上级区域；不传不改。")
    sort_order: int | None = Field(default=None, description="新排序；不传不改。")


class RegionMetaOut(BaseModel):
    """与 SQLite 行一致，供 OpenAPI / 客户端生成类型。"""

    id: str = Field(description="区域主键。")
    name: str = Field(description="展示名称。")
    desc: str = Field(description="说明文字。")
    parent_id: str = Field(description="上级区域 id，空为顶级。")
    sort_order: int = Field(description="同级排序。")
    created_at: str = Field(description="创建时间 ISO 字符串。")


@router.get(
    "",
    response_model=list[RegionMetaOut],
    summary="列出全部区域",
    description="返回 region 表全部记录，无分页。",
)
@router.get(
    "/",
    response_model=list[RegionMetaOut],
    include_in_schema=False,
)
def list_region_meta() -> list[RegionMetaOut]:
    return get_region_meta_service().list_regions()


@router.post(
    "",
    status_code=201,
    response_model=RegionMetaOut,
    summary="创建区域",
    description="在 region 专用 SQLite 中插入一条区域元数据。",
)
@router.post(
    "/",
    status_code=201,
    response_model=RegionMetaOut,
    include_in_schema=False,
)
def create_region_meta(payload: RegionCreatePayload) -> RegionMetaOut:
    try:
        return get_region_meta_service().create(
            id=payload.id,
            name=payload.name,
            desc=payload.desc,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
        )
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.get(
    "/{id}",
    response_model=RegionMetaOut,
    summary="获取单个区域",
    description="按主键读取区域元数据。",
)
def get_region_meta(id: RegionMetaIdPath) -> RegionMetaOut:
    try:
        return get_region_meta_service().get(id).as_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail="region not found") from None


@router.patch(
    "/{id}",
    response_model=RegionMetaOut,
    summary="更新区域",
    description="部分更新 name/desc，至少传一个字段。",
)
def patch_region_meta(id: RegionMetaIdPath, payload: RegionPatchPayload) -> RegionMetaOut:
    if payload.name is None and payload.desc is None and payload.parent_id is None and payload.sort_order is None:
        raise HTTPException(
            status_code=400,
            detail="at least one field is required",
        )
    try:
        return get_region_meta_service().update(
            id,
            name=payload.name,
            desc=payload.desc,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="region not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/seed/builtin", summary="导入内置演示区域")
def seed_builtin_regions(replace_all: bool = Query(default=False)) -> dict:
    try:
        n = get_region_meta_service().seed_builtin(replace_all=replace_all)
        return {"inserted": n, "replaced": replace_all}
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/{id}",
    status_code=204,
    response_class=Response,
    summary="删除区域",
    description="删除区域并级联清空该区域内的全部设备；存在子区域时拒绝删除。",
)
def delete_region_meta(id: RegionMetaIdPath) -> Response:
    region_svc = get_region_meta_service()
    if region_svc.count_children(id) > 0:
        raise HTTPException(status_code=409, detail="请先删除所有子区域")
    eq_svc = EquipmentService()
    eq_svc.delete_by_region_id(id)
    try:
        region_svc.delete(id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="region not found") from None
    return Response(status_code=204)

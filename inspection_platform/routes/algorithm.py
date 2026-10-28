"""算法实体 HTTP API。"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from inspection_platform.algorithm.service import AlgorithmService

router = APIRouter(prefix="/api/algorithm", tags=["algorithm"])

AlgorithmIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        description="算法主键 algorithm_id，与入库/种子数据一致。",
    ),
]


@lru_cache
def get_algorithm_service() -> AlgorithmService:
    return AlgorithmService()


class AlgorithmCreateBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    algorithm_id: str | None = Field(
        default=None,
        max_length=128,
        description="可选自定义主键；不传则服务端生成。",
    )
    name: str = Field(..., min_length=1, max_length=512, description="算法名称。")
    desc: str = Field(default="", max_length=16000, description="说明。")
    link: str = Field(default="", max_length=2048, description="请求地址或路由。")
    io_schema: dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
        description="出入参 JSON Schema 或业务约定结构。",
    )
    health: str = Field(default="unknown", max_length=64, description="健康/可用性状态字符串。")


class AlgorithmPatchBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, max_length=512)
    desc: str | None = Field(default=None, max_length=16000)
    link: str | None = Field(default=None, max_length=2048)
    io_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    health: str | None = Field(default=None, max_length=64)


@router.get(
    "/",
    summary="列出算法",
    description="分页列出算法实体；可按 health、关键词过滤。",
)
def list_algorithms(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    health: str | None = Query(default=None, description="按 health 精确过滤。"),
    q: str | None = Query(default=None, description="按名称/说明/id 模糊搜索。"),
) -> dict[str, Any]:
    items, total = get_algorithm_service().list_algorithms(
        limit=limit, offset=offset, health=health, q=q
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{algorithm_id}",
    summary="获取单个算法",
)
def get_algorithm(algorithm_id: AlgorithmIdPath) -> dict[str, Any]:
    row = get_algorithm_service().get(algorithm_id)
    if not row:
        raise HTTPException(status_code=404, detail="algorithm not found")
    return row


@router.post(
    "/",
    summary="创建算法",
)
def create_algorithm(body: AlgorithmCreateBody) -> dict[str, Any]:
    try:
        return get_algorithm_service().create(
            algorithm_id=body.algorithm_id,
            name=body.name,
            desc=body.desc,
            link=body.link,
            schema=body.io_schema,
            health=body.health,
        )
    except ValueError as e:
        if "已存在" in str(e):
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise


@router.patch(
    "/{algorithm_id}",
    summary="更新算法",
)
def patch_algorithm(algorithm_id: AlgorithmIdPath, body: AlgorithmPatchBody) -> dict[str, Any]:
    svc = get_algorithm_service()
    row = svc.update(
        algorithm_id,
        name=body.name,
        desc=body.desc,
        link=body.link,
        schema=body.io_schema,
        health=body.health,
    )
    if not row:
        raise HTTPException(status_code=404, detail="algorithm not found")
    return row


@router.delete(
    "/{algorithm_id}",
    summary="删除算法",
)
def delete_algorithm(algorithm_id: AlgorithmIdPath) -> dict[str, Any]:
    ok = get_algorithm_service().delete(algorithm_id)
    if not ok:
        raise HTTPException(status_code=404, detail="algorithm not found")
    return {"deleted": True, "algorithm_id": algorithm_id}


@router.post(
    "/seed/builtin",
    summary="导入内置演示算法种子",
    description="从仓库内 builtin_seed.json 写入/更新 SQLite；可选清空后全量导入。",
)
def seed_builtin(
    replace_all: bool = Query(
        default=False,
        description="为 true 时先 DELETE 全部算法再导入。",
    ),
) -> dict[str, Any]:
    try:
        n = get_algorithm_service().seed_builtin(replace_all=replace_all)
        return {"imported": n, "replace_all": replace_all}
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/invoke/{algorithm_id}",
    summary="模拟调用算法",
    description="占位接口：校验 algorithm 存在后返回固定结构，便于联调。",
)
def invoke_algorithm(
    algorithm_id: AlgorithmIdPath,
    body: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    try:
        return get_algorithm_service().mock_invoke(algorithm_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="algorithm not found") from e


@router.get(
    "/vaio/health",
    summary="vaio-analysis-core 健康检查",
)
def vaio_core_health() -> dict[str, Any]:
    from inspection_platform.algorithm import vaio_client

    try:
        data = vaio_client.health()
        return {"ok": True, "core": data, "base_url": vaio_client._base_url()}
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "base_url": vaio_client._base_url()}


@router.get(
    "/vaio/algorithms",
    summary="读取 vaio 核心算法目录（不落库）",
)
def vaio_core_algorithms() -> dict[str, Any]:
    from inspection_platform.algorithm import vaio_client

    try:
        return vaio_client.list_algorithms()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get(
    "/vaio/algorithms/{vaio_id}",
    summary="读取 vaio 核心单条算法配方",
)
def vaio_core_algorithm_recipe(vaio_id: int) -> dict[str, Any]:
    from inspection_platform.algorithm import vaio_client

    try:
        data = vaio_client.get_algorithm(vaio_id)
        if not data:
            raise HTTPException(status_code=404, detail="algorithm not found")
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post(
    "/vaio/sync",
    summary="从 vaio 核心同步算法到平台目录",
    description="拉取 /v1/algorithms 并 upsert 为 vaio-{id} 记录，供算法管理页展示。",
)
def vaio_sync_to_platform() -> dict[str, Any]:
    from inspection_platform.algorithm import vaio_client

    svc = get_algorithm_service()
    core_ok = False
    try:
        health = vaio_client.health()
        core_ok = health.get("status") == "ok"
    except RuntimeError:
        core_ok = False

    try:
        payload = vaio_client.list_algorithms()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    items = payload.get("algorithms") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    result = svc.sync_from_vaio(items, core_healthy=core_ok)
    result["base_url"] = vaio_client._base_url()
    return result


@router.get(
    "/vaio/mcp-tools",
    summary="vaio MCP 工具清单（Hermes 注册名）",
)
def vaio_mcp_tools() -> dict[str, Any]:
    from inspection_platform.algorithm.vaio_client import VAIO_MCP_TOOLS
    from inspection_platform.algorithm.vaio_hermes import hermes_mcp_config_snippet, vaio_mcp_server_config

    return {
        "server": "vaio_analysis",
        "tools": VAIO_MCP_TOOLS,
        "mcp_config": vaio_mcp_server_config(),
        "config_snippet": hermes_mcp_config_snippet(),
    }


@router.post(
    "/vaio/mcp/register",
    summary="注册 vaio_analysis 到 Hermes ~/.hermes/config.yaml",
)
def vaio_register_hermes_mcp() -> dict[str, Any]:
    from inspection_platform.algorithm.vaio_hermes import register_vaio_mcp_in_hermes_config

    try:
        return register_vaio_mcp_in_hermes_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

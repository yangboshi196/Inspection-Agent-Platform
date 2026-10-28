"""Platform MCP / Hermes 注册 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.post(
    "/register-hermes-mcp",
    summary="注册 inspection_platform MCP 到 Hermes ~/.hermes/config.yaml",
)
def platform_register_hermes_mcp() -> dict[str, Any]:
    from inspection_platform.platform_mcp.hermes_register import register_platform_mcp_in_hermes_config

    try:
        return register_platform_mcp_in_hermes_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

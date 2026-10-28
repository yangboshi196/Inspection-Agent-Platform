"""认证与用户 HTTP API。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from inspection_platform.auth.middleware import get_auth_service
from inspection_platform.auth.permissions import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS, normalize_permissions
from inspection_platform.auth.service import _UNSET

router = APIRouter(prefix="/api/auth", tags=["auth"])

UserIdPath = Annotated[str, Path(min_length=1, max_length=128)]


class LoginBody(BaseModel):
    account: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class UserCreateBody(BaseModel):
    user_id: str | None = Field(default=None, max_length=128)
    account: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=4, max_length=128)
    status: str = Field(default="active", description="active | disabled")
    role_id: str | None = Field(default=None, max_length=128)
    permissions: list[str] = Field(default_factory=lambda: list(DEFAULT_USER_PERMISSIONS))


class UserPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, description="active | disabled")
    password: str | None = Field(default=None, min_length=4, max_length=128)
    role_id: str | None = Field(default=None, max_length=128, description="绑定角色 id；传空字符串解绑")
    permissions: list[str] | None = Field(default=None, description="页面权限 id 列表（未绑定角色时）")


class RoleCreateBody(BaseModel):
    role_id: str | None = Field(default=None, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    permissions: list[str] = Field(default_factory=list)


class RolePatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    permissions: list[str] | None = Field(default=None, description="页面权限 id 列表")


RoleIdPath = Annotated[str, Path(min_length=1, max_length=128)]


@router.post("/login", summary="登录")
def login(body: LoginBody) -> dict[str, Any]:
    svc = get_auth_service()
    try:
        result = svc.login(body.account, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    from inspection_platform.document.region_meta import RegionMetaService

    result["regions"] = RegionMetaService().list_regions()
    return result


@router.get("/bootstrap", summary="会话启动包（用户 + 区域，一次请求）")
def bootstrap_session(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    from inspection_platform.document.region_meta import RegionMetaService

    return {"user": user, "regions": RegionMetaService().list_regions()}


@router.post("/logout", status_code=204, summary="退出登录")
def logout(request: Request) -> Response:
    auth = request.headers.get("Authorization") or ""
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    if token:
        get_auth_service().logout(token)
    return Response(status_code=204)


@router.get("/me", summary="当前用户")
def me(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


@router.get("/permissions", summary="系统页面权限 id 列表")
def list_permissions() -> dict[str, Any]:
    return {"items": list(ALL_PERMISSIONS)}


@router.get("/users/", summary="列出用户")
def list_users(request: Request) -> dict[str, Any]:
    _ = request.state.user
    items = get_auth_service().list_users()
    return {"items": items, "total": len(items)}


@router.post("/users/", status_code=201, summary="创建用户")
def create_user(body: UserCreateBody, request: Request) -> dict[str, Any]:
    _ = request.state.user
    svc = get_auth_service()
    try:
        return svc.create_user(
            user_id=body.user_id,
            account=body.account,
            name=body.name,
            password=body.password,
            permissions=normalize_permissions(body.permissions),
            status=body.status,
            role_id=body.role_id,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.patch("/users/{user_id}", summary="更新用户")
def patch_user(user_id: UserIdPath, body: UserPatchBody, request: Request) -> dict[str, Any]:
    _ = request.state.user
    svc = get_auth_service()
    try:
        patch_kwargs: dict[str, Any] = {
            "name": body.name,
            "status": body.status,
            "password": body.password,
        }
        if body.permissions is not None:
            patch_kwargs["permissions"] = normalize_permissions(body.permissions)
        if "role_id" in body.model_fields_set:
            patch_kwargs["role_id"] = (body.role_id or "").strip() or None
        else:
            patch_kwargs["role_id"] = _UNSET
        row = svc.update_user(user_id, **patch_kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="user not found")
    return row


@router.delete("/users/{user_id}", status_code=204, summary="删除用户")
def delete_user(user_id: UserIdPath, request: Request) -> Response:
    _ = request.state.user
    try:
        ok = get_auth_service().delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="user not found")
    return Response(status_code=204)


@router.get("/roles/", summary="列出角色")
def list_roles(request: Request) -> dict[str, Any]:
    _ = request.state.user
    items = get_auth_service().list_roles()
    return {"items": items, "total": len(items)}


@router.post("/roles/", status_code=201, summary="创建角色")
def create_role(body: RoleCreateBody, request: Request) -> dict[str, Any]:
    _ = request.state.user
    svc = get_auth_service()
    try:
        return svc.create_role(
            role_id=body.role_id,
            name=body.name,
            description=body.description,
            permissions=normalize_permissions(body.permissions),
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.patch("/roles/{role_id}", summary="更新角色")
def patch_role(role_id: RoleIdPath, body: RolePatchBody, request: Request) -> dict[str, Any]:
    _ = request.state.user
    svc = get_auth_service()
    try:
        row = svc.update_role(
            role_id,
            name=body.name,
            description=body.description,
            permissions=normalize_permissions(body.permissions) if body.permissions is not None else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="role not found")
    return row


@router.delete("/roles/{role_id}", status_code=204, summary="删除角色")
def delete_role(role_id: RoleIdPath, request: Request) -> Response:
    _ = request.state.user
    try:
        ok = get_auth_service().delete_role(role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="role not found")
    return Response(status_code=204)


@router.post("/seed/builtin", summary="导入内置演示用户")
def seed_builtin_users() -> dict[str, Any]:
    n = get_auth_service().seed_builtin()
    return {"inserted": n}

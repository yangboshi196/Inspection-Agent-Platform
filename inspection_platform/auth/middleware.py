"""全局 API 鉴权中间件。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from inspection_platform.auth.guard import required_permission
from inspection_platform.auth.service import AuthService

PUBLIC_ROUTES: set[tuple[str, str]] = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/seed/builtin"),
    ("GET", "/api/health"),
}

AUTH_COOKIE_NAME = "SIA_auth_token"

# 鉴权专用线程池，避免与业务 sync 路由争抢默认 executor 导致 /me、/region 集体挂起。
_AUTH_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="sia-auth")

_AUTH_RESOLVE_TIMEOUT_SEC = 5.0


def _allows_browser_stream_auth(path: str, method: str) -> bool:
    """浏览器 img/video/iframe 无法带 Authorization，允许 query/cookie 鉴权。"""
    if method != "GET":
        return False
    return "/live/" in path or path.startswith("/api/media/")


def _token_from_browser_request(request: Request) -> str | None:
    from urllib.parse import unquote

    q = request.query_params.get("access_token") or request.query_params.get("token")
    token = (q or "").strip()
    if token:
        return token
    cookie = (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    if cookie:
        return unquote(cookie) or None
    return None


@lru_cache
def get_auth_service() -> AuthService:
    """勿在中间件同步路径调用 ensure_ready/init_db，否则会阻塞 asyncio 事件循环。"""
    return AuthService()


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path.rstrip("/") or "/"
        method = request.method.upper()

        if not path.startswith("/api"):
            return await call_next(request)
        if method == "OPTIONS":
            return await call_next(request)
        if (method, path) in PUBLIC_ROUTES:
            return await call_next(request)

        svc = get_auth_service()
        token = _extract_bearer(request.headers.get("Authorization"))
        if not token and _allows_browser_stream_auth(request.url.path, method):
            token = _token_from_browser_request(request)
        # resolve_token 走 MySQL 同步 IO，须 offload；并限制等待时间避免刷新时全站挂起。
        try:
            loop = asyncio.get_running_loop()
            user = await asyncio.wait_for(
                loop.run_in_executor(_AUTH_EXECUTOR, svc.resolve_token, token),
                timeout=_AUTH_RESOLVE_TIMEOUT_SEC,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return JSONResponse(
                status_code=503,
                content={"detail": "鉴权服务繁忙，请稍后刷新"},
            )
        if not user:
            return JSONResponse(status_code=401, content={"detail": "未登录或会话已过期"})
        if user.get("status") != "active":
            return JSONResponse(status_code=403, content={"detail": "账号已停用"})

        perm = required_permission(path, method)
        permissions = user.get("permissions") or []
        if perm and perm not in permissions:
            return JSONResponse(status_code=403, content={"detail": "无权限访问该资源"})

        request.state.user = user
        return await call_next(request)

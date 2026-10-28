"""流媒体中台状态与 go2rtc 资源代理。"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from starlette.websockets import WebSocketState

from inspection_platform.auth.guard import required_permission
from inspection_platform.auth.middleware import AUTH_COOKIE_NAME, get_auth_service
from inspection_platform.media.config import go2rtc_api_base
from inspection_platform.media.service import get_media_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])


def _ws_auth_token(websocket: WebSocket) -> str | None:
    """go2rtc stream.html 的 WebSocket 不带 query token，需与 HTTP 一致支持 cookie。"""
    token = (
        websocket.query_params.get("access_token") or websocket.query_params.get("token") or ""
    ).strip()
    if token:
        return token
    cookie = (websocket.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    if cookie:
        return urllib.parse.unquote(cookie) or None
    return None


def _ws_auth_ok(websocket: WebSocket) -> bool:
    """WebSocket 不走 HTTP 中间件，在此校验 token 与权限。"""
    token = _ws_auth_token(websocket)
    user = get_auth_service().resolve_token(token)
    if not user or user.get("status") != "active":
        return False
    perm = required_permission(websocket.url.path, "GET")
    permissions = user.get("permissions") or []
    if perm and perm not in permissions:
        return False
    websocket.state.user = user
    return True


def _go2rtc_upstream_http(path: str, query: str) -> str:
    base = go2rtc_api_base().rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    if query:
        return f"{url}?{query}"
    return url


def _go2rtc_upstream_ws(path: str, query: str) -> str:
    http = _go2rtc_upstream_http(path, query)
    if http.startswith("https://"):
        return "wss://" + http[len("https://") :]
    if http.startswith("http://"):
        return "ws://" + http[len("http://") :]
    return http


def _strip_auth_query(query_params: Any) -> str:
    pairs = [(k, v) for k, v in query_params.multi_items() if k not in ("access_token", "token")]
    return urllib.parse.urlencode(pairs)


@router.get("/status", summary="流媒体中台状态")
def media_status() -> dict[str, Any]:
    svc = get_media_service()
    alive = svc._client.is_alive()  # noqa: SLF001
    return {
        "backend": svc.backend(),
        "go2rtc_api": go2rtc_api_base(),
        "go2rtc_alive": alive,
    }


@router.api_route("/go2rtc/{path:path}", methods=["GET", "HEAD"], summary="代理 go2rtc 静态/页面")
async def proxy_go2rtc(path: str, request: Request) -> Response:
    """供 WebRTC embed 加载 go2rtc stream.html 等静态资源（内网）。"""
    qs = _strip_auth_query(request.query_params)
    upstream = _go2rtc_upstream_http(path, qs)
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(request.method, upstream) as resp:
            headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in ("transfer-encoding", "connection", "content-encoding")
            }
            if request.method == "HEAD":
                return Response(status_code=resp.status_code, headers=headers)
            body = await resp.aread()
            token = (
                request.query_params.get("access_token")
                or request.query_params.get("token")
                or ""
            ).strip()
            norm_path = path.lstrip("/")
            if token and norm_path == "stream.html" and b"</head>" in body:
                inject = (
                    "<script>(function(){"
                    "var p=new URLSearchParams(location.search);"
                    "var T=p.get('access_token')||p.get('token');"
                    "if(!T)return;"
                    "var N=WebSocket;"
                    "window.WebSocket=function(u,proto){"
                    "if(typeof u==='string'){try{"
                    "var x=new URL(u,location.href);"
                    "if(!x.searchParams.has('access_token'))"
                    "x.searchParams.set('access_token',T);"
                    "u=x.toString();}catch(e){}}"
                    "return new N(u,proto);};"
                    "window.WebSocket.prototype=N.prototype;"
                    "})();</script>"
                )
                body = body.replace(b"</head>", inject.encode("utf-8") + b"</head>", 1)
            return Response(content=body, status_code=resp.status_code, headers=headers)


@router.websocket("/go2rtc/{path:path}")
async def proxy_go2rtc_ws(websocket: WebSocket, path: str) -> None:
    """代理 go2rtc WebSocket（stream.html WebRTC/MSE 必需）。"""
    if not _ws_auth_ok(websocket):
        await websocket.close(code=4401, reason="未登录或无权限")
        return

    qs = _strip_auth_query(websocket.query_params)
    upstream_url = _go2rtc_upstream_ws(path, qs)
    await websocket.accept()

    try:
        async with websockets.connect(upstream_url, open_timeout=10, close_timeout=5) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while websocket.client_state == WebSocketState.CONNECTED:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                async for payload in upstream:
                    if websocket.client_state != WebSocketState.CONNECTED:
                        break
                    if isinstance(payload, bytes):
                        await websocket.send_bytes(payload)
                    else:
                        await websocket.send_text(payload)

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                    logger.debug("go2rtc ws proxy task ended: %s", exc)
    except Exception as exc:
        logger.warning("go2rtc ws proxy failed path=%s: %s", path, exc)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011, reason="go2rtc ws upstream failed")

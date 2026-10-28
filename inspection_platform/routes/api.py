"""REST + SSE 接口定义。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from inspection_platform.deps import get_agent
from inspection_platform.schemas import ChatBody

router = APIRouter(prefix="/api", tags=["api"])


@router.get(
    "/health",
    summary="健康检查",
    description="返回服务存活状态，供负载均衡或监控探活。",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/chat/stream",
    summary="主 Agent 流式对话",
    description="Server-Sent Events：按行推送 JSON 事件（含模型回复、工具调用等）。请求体为 ChatBody。",
)
def api_chat_stream(body: ChatBody) -> StreamingResponse:
    agent = get_agent()
    user_text = body.message.strip()

    def gen() -> Iterator[str]:
        try:
            for ev in agent.stream(
                session_id=body.session_id.strip(),
                user_input=user_text,
                model_name=None,
                record_user_message=True,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

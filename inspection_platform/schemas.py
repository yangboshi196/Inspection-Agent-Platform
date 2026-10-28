"""HTTP 请求体模型（平台 API）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatBody(BaseModel):
    session_id: str = Field(
        ...,
        min_length=4,
        max_length=128,
        description="会话标识；同一 id 多轮对话共享上下文。建议使用随机字符串或业务会话号。",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=32000,
        description="用户本轮输入的纯文本；由主 Agent（ReAct）处理并流式返回 SSE 事件。",
    )

"""
SIA_agent.llm.errors - LLM 层错误类型

定义 LLM 调用失败时的结构化异常：
- LLMErrorCode：错误码枚举（AUTH_FAILED / RATE_LIMITED / TIMEOUT / NETWORK_ERROR 等）
- LLMError：LLM 调用失败时抛出的结构化异常（含错误码、是否可重试）
- redact_secrets()：日志脱敏工具，将敏感字符串替换为 "****"

注意：本模块定义的是 LLM 层错误；统一异常体系请使用 `SIA_agent.errors`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


LLMErrorCode = Literal[
    "AUTH_FAILED",
    "RATE_LIMITED",
    "TIMEOUT",
    "NETWORK_ERROR",
    "MODEL_UNAVAILABLE",
    "INPUT_TOO_LARGE",
    "BAD_REQUEST",
    "UNKNOWN",
]


@dataclass
class LLMError(Exception):
    """LLM 调用失败时抛出的结构化异常，含错误码、是否可重试及上游原始信息。"""

    code: LLMErrorCode
    message: str
    retryable: bool = False
    provider: str | None = None
    request_id: str | None = None
    raw: Any | None = None

    def __str__(self) -> str:  # noqa: D105
        provider = f" provider={self.provider}" if self.provider else ""
        request_id = f" request_id={self.request_id}" if self.request_id else ""
        return f"LLMError(code={self.code}{provider}{request_id}): {self.message}"


def redact_secrets(text: str, secrets: list[str]) -> str:
    """将 `text` 中出现的任一 `secrets` 子串替换为 `****`，用于日志脱敏。"""
    redacted = text
    for s in secrets:
        if not s:
            continue
        redacted = redacted.replace(s, "****")
    return redacted


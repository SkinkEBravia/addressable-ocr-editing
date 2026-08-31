"""llm 模块的统一错误类型。

LLMError 携带可诊断字段（HTTP status、已尝试次数），
但绝不携带 API key、Authorization 头等敏感信息。
"""

from __future__ import annotations

__all__ = ["LLMError"]


class LLMError(Exception):
    """LLM 访问失败。

    属性：
        status:   HTTP 状态码（网络错误 / 解析失败时为 None）。
        attempts: 已发起的请求次数（含首次，1 表示未发生重试）。
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        attempts: int = 0,
    ) -> None:
        self.message = message
        self.status = status
        self.attempts = attempts
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [self.message]
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.attempts:
            parts.append(f"attempts={self.attempts}")
        return "；".join(parts)

"""llm 的错误类型。

对应 Docs/Design/08-llm.md「错误与重试」节。
"""

from __future__ import annotations

__all__ = ["LLMError", "ConfigError", "CredentialError"]


class LLMError(Exception):
    """LLM 调用失败。

    kind: timeout | rate_limit | server | auth | bad_response。
    安全约束：API key 不进入异常消息。
    """

    KINDS = ("timeout", "rate_limit", "server", "auth", "bad_response")

    def __init__(
        self,
        message: str,
        *,
        kind: str = "bad_response",
        status: int | None = None,
        attempts: int = 1,
    ) -> None:
        if kind not in self.KINDS:
            raise ValueError(f"unknown LLMError kind: {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.attempts = attempts


class ConfigError(Exception):
    """模型 / 工具配置错误：未知键、协议不支持的采样键、未实现的协议等。"""


class CredentialError(Exception):
    """凭证缺失：key_env 未设置。不发请求。"""

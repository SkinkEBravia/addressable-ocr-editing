"""LLMClient 协议与 build_client 工厂。

对应 Docs/Design/08-llm.md「输入输出接口」「LiteLLM 接入方案」节。

调用方只依赖项目接口；具体 SDK 与协议处理由 LiteLLMClient 封装。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from llm.config import ModelConfig, PROTOCOLS, resolve_api_key
from llm.errors import ConfigError
from llm.types import Completion, Message

__all__ = ["LLMClient", "build_client"]


class LLMClient(Protocol):
    """同步补全接口。无状态：对话历史由调用方持有。

    on_delta 非空时启用流式输出，每个文本增量回调（过程可观测）。
    失败时抛 llm.errors.LLMError / CredentialError / ConfigError。
    """

    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: "Callable[[str], None] | None" = None,
    ) -> Completion: ...


def build_client(config: ModelConfig) -> LLMClient:
    """构造 SDK 封装；未知协议报 ConfigError，不静默降级。"""
    if config.protocol not in PROTOCOLS:
        raise ConfigError(f"未知 protocol {config.protocol!r}")
    from llm.litellm_client import LiteLLMClient

    return LiteLLMClient(config, resolve_api_key(config))

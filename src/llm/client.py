"""LLMClient 协议与 build_client 工厂。

对应 Docs/Design/08-llm.md「接口」「协议适配器」节。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from llm.config import ModelConfig, resolve_api_key
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
    """按 protocol 分派适配器。未实现的协议报 ConfigError，不静默降级。"""
    if config.protocol == "openai-completion":
        from llm.adapters.openai_completion import OpenAICompletionClient

        return OpenAICompletionClient(config, resolve_api_key(config))
    raise ConfigError(
        f"protocol {config.protocol!r} 的适配器尚未实现（v1 仅 openai-completion）"
    )

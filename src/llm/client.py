"""LLM 访问层协议与结果类型。

测评装配层（experiment_app）只依赖本文件定义的 LLMClient 协议，
不感知具体供应商实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["Usage", "Completion", "LLMClient"]


@dataclass(frozen=True)
class Usage:
    """单次调用的 token 计数。

    契约：必须来自服务端返回的 usage 字段，不允许客户端估算。
    """

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    """单次补全的结果：文本 + 真实 token 计数。"""

    text: str
    usage: Usage


class LLMClient(Protocol):
    """同步补全接口。失败时抛 llm.errors.LLMError。"""

    def complete(self, prompt: str, *, system: str | None = None) -> Completion: ...

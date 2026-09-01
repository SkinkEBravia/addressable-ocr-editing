"""StubClient：录制回放的测试夹具。

StubClient 是一个假端点——它返回的 usage 由假端点自己计数（空白切分），
不违反「usage 来自端点」的契约（它就是端点）。用于 golden 测试与
experiment 的冒烟（见 Docs/Design/11-experiment.md「验收」）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from llm.types import Completion, Message, Usage

__all__ = ["StubClient"]

# str（返回该文本）| Exception（抛出）| 回调 messages -> str
_ScriptEntry = str | Exception | Callable[[list[Message]], str]


def _fake_usage(messages: list[Message], text: str) -> Usage:
    """假端点的计数：空白切分。仅用于 stub，不进真实报告口径。"""
    in_tokens = sum(len(m.content.split()) for m in messages)
    return Usage(input_tokens=in_tokens, output_tokens=max(1, len(text.split())))


class StubClient:
    """按剧本逐轮返回响应的 LLMClient。

    - script 用尽后再被调用 -> RuntimeError。
    - 记录每次调用的 messages（``calls``），供测试断言对话内容。
    """

    def __init__(self, script: Sequence[_ScriptEntry]) -> None:
        self._script = list(script)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> Completion:
        self.calls.append(list(messages))
        if not self._script:
            raise RuntimeError("StubClient 剧本已用尽")
        entry = self._script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        text = entry(messages) if callable(entry) else entry
        return Completion(text=text, usage=_fake_usage(messages, text), raw={"stub": True})

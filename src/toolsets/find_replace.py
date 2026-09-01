"""标准工具配置：find_replace（常见 harness 最小编辑工具的复刻）。

对应 Docs/Design/09-tools.md「标准工具配置」节。

工具：read() / find_replace(old, new)（replace-all 语义，与 str.replace 一致）。
方言：一行一调用；done() 单独一行 = Done。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from toolsets.core import DONE, Done, ToolCall, ToolContext, ToolParseError, ToolResult

__all__ = ["FindReplaceToolSet", "FIND_REPLACE_CLAUSE"]

FIND_REPLACE_CLAUSE = """\
You edit the text with tool calls, one function call per line:
- read() — return the current full text
- find_replace("old", "new") — replace EVERY occurrence of "old" in the whole text with "new" (replace-all). "old" must be copied VERBATIM from the text; if it does not occur exactly, the call fails. Keep "old" as SHORT as possible while still unambiguous — every character you quote costs output tokens
- done() — finish; the current text becomes the output

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\Z", re.DOTALL)
_KNOWN = ("read", "find_replace")


class FindReplaceToolSet:
    """read / find_replace 两个工具；ToolContext 持有当前文本。"""

    name = "find_replace"
    uses_llm = True
    prompt_clause = FIND_REPLACE_CLAUSE

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext:
        return ToolContext(workdir=workdir, data={"text": task_input})

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        calls: list[ToolCall] = []
        for lineno, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "done()":
                if calls:
                    raise ToolParseError(
                        f"line {lineno}: done() must be the only content of a message"
                    )
                return DONE
            m = _CALL_RE.match(line)
            if m is None:
                raise ToolParseError(f"line {lineno}: expected `name(args)`, got {line!r}")
            name, args_text = m.group(1), m.group(2)
            if name not in _KNOWN:
                raise ToolParseError(
                    f"line {lineno}: unknown tool {name!r} (known: {', '.join(_KNOWN)}, done)"
                )
            calls.append(ToolCall(name, args_text.strip()))
        if not calls:
            raise ToolParseError("empty response; emit tool calls or done()")
        return tuple(calls)

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        if call.name == "read":
            return ToolResult(True, ctx.data["text"])
        if call.name == "find_replace":
            return self._find_replace(call, ctx)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, ctx: ToolContext) -> str:
        return ctx.data["text"]

    # -- 内部 -------------------------------------------------------------

    def _find_replace(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        try:
            old, new = _parse_two_strings(call.args_text)
        except ToolParseError as exc:
            return ToolResult(False, f"find_replace: {exc}")
        text: str = ctx.data["text"]
        count = text.count(old)
        if count == 0:
            return ToolResult(False, f"PATTERN_NOT_FOUND: {old!r} does not occur")
        ctx.data["text"] = text.replace(old, new)
        return ToolResult(True, f"replaced {count} occurrence(s)")


def _parse_two_strings(args_text: str) -> tuple[str, str]:
    """解析两个 JSON 字符串参数（受控解析，无 eval）。"""
    decoder = json.JSONDecoder()
    pos = 0
    values: list[str] = []
    n = len(args_text)
    while len(values) < 2:
        while pos < n and args_text[pos] in " \t":
            pos += 1
        try:
            value, pos = decoder.raw_decode(args_text, pos)
        except json.JSONDecodeError as exc:
            raise ToolParseError(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(value, str):
            raise ToolParseError(f"argument must be a JSON string, got {value!r}")
        values.append(value)
        while pos < n and args_text[pos] in " \t":
            pos += 1
        if len(values) < 2:
            if pos >= n or args_text[pos] != ",":
                raise ToolParseError("expected ',' between arguments")
            pos += 1
    while pos < n and args_text[pos] in " \t":
        pos += 1
    if pos < n:
        raise ToolParseError("find_replace takes exactly 2 arguments")
    return values[0], values[1]

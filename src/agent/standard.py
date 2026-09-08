"""标准工具配置：noop / rewrite / find_replace。

对应 Docs/Design/09-tools.md「标准工具配置」节。

- noop：no-correction 锚点对照，不调 LLM，output = input。
- rewrite：空工具集，单轮全文重写；fold 状态即对话本身，extract 读 session.turns。
- find_replace：read / find_replace 两个工具（常见 harness 最小编辑工具的复刻）。
- *_anthropic_style：实验「交付方式」的两个臂——path 抬头视图 +
  对齐 Anthropic str_replace 的唯一匹配语义（见 plan/neo_experiment.md）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.session import Session
from agent.toolset import DONE, Done, ToolCall, ToolParseError, ToolResult
from sourceio import SourceText
from view import file_header

__all__ = [
    "NoopToolSet",
    "RewriteToolSet",
    "FindReplaceToolSet",
    "RewriteAnthropicToolSet",
    "FindReplaceAnthropicToolSet",
    "REWRITE_CLAUSE",
    "FIND_REPLACE_CLAUSE",
    "FIND_REPLACE_ANTHROPIC_CLAUSE",
    "ONE_SHOT_NOTICE",
    "ONE_SHOT_NOTICE_TOOLS",
    "ONE_SHOT_NOTICE_REWRITE",
    "PATH_NAME",
    "extract_rewrite_text",
]

PATH_NAME = "text"
"""单文档场景唯一的 path 名（跨轮稳定）；与 path 抬头 --- [Text: text] --- 对应。"""

ONE_SHOT_NOTICE = """\
You have only ONE chance: this task gives you a single response — no feedback, no retry, no second turn."""
"""1-shot 臂的一次性告知：逐字追加在 prompt_clause 最后（plan/neo_experiment.md 实验组口径）。"""

ONE_SHOT_NOTICE_TOOLS = ONE_SHOT_NOTICE + "\nEmit ALL your calls in this one response, with done() as the last line."
"""工具臂版：一口气给出全部调用，done() 收尾。"""

ONE_SHOT_NOTICE_REWRITE = ONE_SHOT_NOTICE + "\nEmit the complete output in this one response."
"""rewrite 臂版：一口气给出完整产出。"""


def _source(text: str) -> SourceText:
    """模型产出的 SourceText：无 BOM、UTF-8（与任务输入的装载口径一致）。"""
    return SourceText(text=text, encoding="utf-8", bom=b"")


# ---------------------------------------------------------------- noop


class NoopToolSet:
    """no-correction 锚点对照：不调 LLM，output = input。"""

    name = "noop"
    uses_llm = False
    prompt_clause = ""

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        return {"input": task_input}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        return DONE

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return _source(tool_state["input"])


# ---------------------------------------------------------------- rewrite

# rewrite 的输出条款（BLOCR 原样：JSON 输出 + CORRECTIONS_CSV 日志，
# CSV 是 BLOCR 原样的 token 成本，保留）。
REWRITE_CLAUSE = """\
Return a JSON object with exactly one field: "ocr_postcorrection_output".
Return ONLY valid JSON. No explanation, no preamble, no markdown fences.

After the JSON object, output a CSV corrections log.
Marker line: CORRECTIONS_CSV
Columns: document_id,ocr_hypothesis_snippet,ocr_postcorrection_snippet,error_type,confidence,notes
- error_type: over_segmentation, misrecognized_char, under_segmentation, missing_character, wrong_word, uncertain, no_change, or custom:label
- confidence: high, medium, or low
- One row per document_id (use no_change if unchanged)
- Do not wrap the CSV in markdown fences"""


def extract_rewrite_text(text: str) -> str:
    """rewrite 产出提取：解析首个 JSON 对象的 ocr_postcorrection_output 字段
    （尾部 CORRECTIONS_CSV 日志忽略）；失败则剥 markdown 围栏；再失败用原文。"""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.split("\n")
        lines = lines[1:] if len(lines) > 1 else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        obj, _ = json.JSONDecoder().raw_decode(candidate)
        if isinstance(obj, dict) and isinstance(out := obj.get("ocr_postcorrection_output"), str):
            return out
    except ValueError:
        pass
    return text


class RewriteToolSet:
    """空工具集：单轮全文重写，extract = 末轮 assistant 文本（解析 JSON 条款）。"""

    name = "rewrite"
    uses_llm = True
    prompt_clause = REWRITE_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        return {}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        # 空工具集：任何非空响应都直接完成（空响应已被 08 的 client 层拦截）
        if not text.strip():
            raise ToolParseError("empty response")
        return DONE

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        text = session.turns[-1].completion.text if session.turns else ""
        return _source(extract_rewrite_text(text))


# ---------------------------------------------------------------- find_replace

FIND_REPLACE_CLAUSE = """\
You edit the text with tool calls, one function call per line:
- read() — return the current full text
- find_replace("old", "new") — replace EVERY occurrence of "old" in the whole text with "new" (replace-all). "old" must be copied VERBATIM from the text; if it does not occur exactly, the call fails. Keep "old" as SHORT as possible while still unambiguous — every character you quote costs output tokens
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\Z", re.DOTALL)
_KNOWN = ("read", "find_replace")


class FindReplaceToolSet:
    """read / find_replace 两个工具；tool_state 持有当前文本。"""

    name = "find_replace"
    uses_llm = True
    prompt_clause = FIND_REPLACE_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        return {"text": task_input}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        calls: list[ToolCall] = []
        lines = text.split("\n")
        # 末尾标记：最后一行是 done()/done ⇒ 先执行前面的调用再收束
        trailing_done = False
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() in ("done()", "done"):
            trailing_done = True
            lines.pop()
        for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line in ("done()", "done"):
                raise ToolParseError(
                    f"line {lineno}: done() 只能出现在消息最后一行"
                )
            m = _CALL_RE.match(line)
            if m is None:
                raise ToolParseError(f"line {lineno}: expected `name(args)`, got {line!r}")
            name, args_text = m.group(1), m.group(2)
            if name not in _KNOWN:
                raise ToolParseError(
                    f"line {lineno}: unknown tool {name!r} (known: {', '.join(_KNOWN)}, done)"
                )
            calls.append(ToolCall(name, args_text.strip()))
        if trailing_done:
            calls.append(ToolCall("done"))
        if not calls:
            raise ToolParseError("empty response; emit tool calls or done()")
        return tuple(calls)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name == "done":
            return ToolResult(True, "", finish=True)
        if call.name == "read":
            return ToolResult(True, tool_state["text"])
        if call.name == "find_replace":
            return self._find_replace(call, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return _source(tool_state["text"])

    # -- 内部 -------------------------------------------------------------

    def _find_replace(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            old, new = _parse_two_strings(call.args_text)
        except ToolParseError as exc:
            return ToolResult(False, f"find_replace: {exc}")
        text: str = tool_state["text"]
        count = text.count(old)
        if count == 0:
            return ToolResult(False, f"PATTERN_NOT_FOUND: {old!r} does not occur")
        tool_state["text"] = text.replace(old, new)
        return ToolResult(True, f"replaced {count} occurrence(s)")


def _parse_two_strings(args_text: str) -> tuple[str, str]:
    """解析两个 JSON 字符串参数（受控解析，无 eval）。"""
    try:
        parsed = json.loads(f"[{args_text}]")
    except json.JSONDecodeError as exc:
        raise ToolParseError(f"invalid JSON: {exc.msg}") from exc
    match parsed:
        case [str(first), str(second)]:
            return first, second
        case [*args] if len(args) != 2:
            raise ToolParseError("find_replace takes exactly 2 arguments")
        case [first, _] if not isinstance(first, str):
            raise ToolParseError(f"argument must be a JSON string, got {first!r}")
        case [_, second]:
            raise ToolParseError(f"argument must be a JSON string, got {second!r}")


# ---------------------------------------------------------------- find_replace（Anthropic 风格）

FIND_REPLACE_ANTHROPIC_CLAUSE = """\
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path`
- find_replace(path, "old", "new") — replace "old" with "new" in `path`. "old" must be copied VERBATIM from the text and must match EXACTLY ONE place in `path`. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

_PATH_ARG_RE = re.compile(
    r'\s*("[^"\\]*(?:\\.[^"\\]*)*"|[A-Za-z0-9_.\-/]+)\s*(?:,(.*))?\Z', re.DOTALL
)


def _parse_path_and_rest(args_text: str) -> tuple[str, str]:
    """拆分首个 path 参数（裸标识符或 JSON 字符串，同 fn 方言的 id 规则）
    与剩余参数文本。"""
    m = _PATH_ARG_RE.match(args_text)
    if m is None:
        raise ToolParseError("expected path as first argument")
    token = m.group(1)
    if token.startswith('"'):
        try:
            path = json.loads(token)
        except json.JSONDecodeError as exc:
            raise ToolParseError(f"invalid JSON string: {exc.msg}") from exc
        if not isinstance(path, str):
            raise ToolParseError(f"path must be a string, got {path!r}")
    else:
        path = token
    return path, (m.group(2) or "").strip()


def _unknown_path(path: str) -> str:
    return f"unknown path {path!r}; the only path in this session is {PATH_NAME!r}"


class FindReplaceAnthropicToolSet:
    """read(path) / find_replace(path, "old", "new")：对齐 Anthropic str_replace
    的唯一性语义——old 在整个 path 内必须恰好出现一次（0 或 >1 都拒绝执行
    并回报冲突数），与 FindReplaceToolSet 的 replace-all 语义相对。

    输入呈现带 path 抬头；tool_state 持有当前文本（与 FindReplaceToolSet 同）。
    """

    name = "find_replace_anthropic_style"
    uses_llm = True
    prompt_clause = FIND_REPLACE_ANTHROPIC_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_TOOLS

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        return {"text": task_input}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return file_header("Text", PATH_NAME) + task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        calls: list[ToolCall] = []
        lines = text.split("\n")
        # 末尾标记：最后一行是 done()/done ⇒ 先执行前面的调用再收束
        trailing_done = False
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() in ("done()", "done"):
            trailing_done = True
            lines.pop()
        for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line in ("done()", "done"):
                raise ToolParseError(
                    f"line {lineno}: done() 只能出现在消息最后一行"
                )
            m = _CALL_RE.match(line)
            if m is None:
                raise ToolParseError(f"line {lineno}: expected `name(args)`, got {line!r}")
            name, args_text = m.group(1), m.group(2)
            if name not in _KNOWN_ANTHROPIC:
                raise ToolParseError(
                    f"line {lineno}: unknown tool {name!r} "
                    f"(known: {', '.join(_KNOWN_ANTHROPIC)}, done)"
                )
            calls.append(ToolCall(name, args_text.strip()))
        if trailing_done:
            calls.append(ToolCall("done"))
        if not calls:
            raise ToolParseError("empty response; emit tool calls or done()")
        return tuple(calls)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name == "done":
            return ToolResult(True, "", finish=True)
        if call.name == "read":
            try:
                path, rest = _parse_path_and_rest(call.args_text)
            except ToolParseError as exc:
                return ToolResult(False, f"read: {exc}")
            if rest:
                return ToolResult(False, "read: takes exactly 1 argument (path)")
            if path != PATH_NAME:
                return ToolResult(False, f"read: {_unknown_path(path)}")
            return ToolResult(True, tool_state["text"])
        if call.name == "find_replace":
            return self._find_replace(call, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return _source(tool_state["text"])

    # -- 内部 -------------------------------------------------------------

    def _find_replace(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            path, rest = _parse_path_and_rest(call.args_text)
            old, new = _parse_two_strings(rest)
        except ToolParseError as exc:
            return ToolResult(False, f"find_replace: {exc}")
        if path != PATH_NAME:
            return ToolResult(False, f"find_replace: {_unknown_path(path)}")
        text: str = tool_state["text"]
        count = text.count(old)
        if count == 0:
            return ToolResult(False, f"PATTERN_NOT_FOUND: {old!r} does not occur")
        if count > 1:
            return ToolResult(
                False,
                f"Found {count} matches for {old!r}. "
                "Please provide more context to make a unique match.",
            )
        tool_state["text"] = text.replace(old, new)
        return ToolResult(True, "replaced 1 occurrence")


_KNOWN_ANTHROPIC = ("read", "find_replace")


class RewriteAnthropicToolSet(RewriteToolSet):
    """rewrite 的 path 抬头变体：输入呈现带 --- [Text: text] --- 抬头，
    输出解析不变（单轮全文重写）；条款 = REWRITE_CLAUSE + 1-shot 告知。"""

    name = "rewrite_anthropic_style"
    prompt_clause = REWRITE_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_REWRITE

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return file_header("Text", PATH_NAME) + task_input

"""标准工具配置：swe_edit（经典 SWE-agent v0.7 行号锚编辑，构建在 IR 之上）。

对应 Docs/Design/09-tools.md「标准工具配置」节；语义参照
related_agents/swe-agent-classic/config/commands/edit_linting.sh（MIT）。

- 操作面 = IR 公开接口：partition_lines 分块（每行一块），id 策略
  ``line_number``（AgentBlockId = 行号，1 起），标注 ``cat_n``（N: 内容）。
- `edit(start, end, "text")` 把 [start, end]（含两端）整段替换为 text
  （行数可增可减）：降解 = Remove 覆盖块 + Append 替换行（逐行一块）。
  行号是位置性 id——编辑后漂移，下一次 View 重排；BlockKey 不进对话。
- 与 patch（块 id 锚）/ find_replace（字符串锚）互为锚点类型对照；
  提示词行文沿用 v0.7 原版风格。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import ir
import partition
import reconstruction
import sourceio
import view as view_mod
from agent.session import Session
from agent.toolset import DONE, Done, ToolCall, ToolParseError, ToolResult
from sourceio import SourceText

__all__ = ["SweEditToolSet", "SWE_EDIT_CLAUSE"]

SWE_EDIT_CLAUSE = """\
You are working directly in the command line with a special interface. The interface consists of a file editor that shows you the text with line numbers.

COMMANDS (one function call per line):
- view() — print the text with line numbers
- edit(<start_line>, <end_line>, "<text>") — replaces lines <start_line> through <end_line> (INCLUSIVE, 1-based) with the given text. All of the replacement text will be entered literally, so make sure your whitespace is exact. The replacement may span multiple lines (use \\n in the JSON string). Line numbers are the ones shown by view(). Keep the replaced range as SMALL as possible while covering the error — every line you quote costs output tokens. After an edit, line numbers below the edited region shift; re-view() if you need fresh numbers
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Numbers are plain integers; the replacement text uses JSON string syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\Z", re.DOTALL)
_KNOWN = ("view", "edit")


class SweEditToolSet:
    """view / edit(start, end, text) 两个工具；tool_state 持有 IR store + 内存快照。

    落盘节奏同 numkey 臂（见 09「工具契约」flush 条）：轮内编辑只推进
    内存快照，轮末由 loop 调 flush 一次性落盘。"""

    name = "swe_edit"
    uses_llm = True
    prompt_clause = SWE_EDIT_CLAUSE

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        store = ir.Store(workdir / "session")
        source = sourceio.SourceText(text=task_input, encoding="utf-8", bom=b"")
        snapshot = ir.birth(source, partition.partition_lines(source))
        ir.save(store, snapshot)  # 初始快照落盘（审计起点）
        return {"store": store, "snapshot": snapshot}

    def flush(self, tool_state: dict) -> None:
        """轮末持久化钩子（loop 在每轮 on_turn 前调用）。"""
        ir.save(tool_state["store"], tool_state["snapshot"])

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._view(tool_state)

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
        if call.name == "view":
            return ToolResult(True, self._view(tool_state))
        if call.name == "edit":
            return self._edit(call, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return reconstruction.reconstruct(tool_state["snapshot"])

    # -- 内部 -------------------------------------------------------------

    def _view(self, tool_state: dict) -> str:
        snapshot = tool_state["snapshot"]  # 内存快照（轮末 flush 才落盘）
        agent_view = view_mod.present(
            snapshot, view_mod.line_number, view_mod.cat_n
        )
        return agent_view.payload

    def _edit(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            start, end, text = _parse_edit_args(call.args_text)
        except ToolParseError as exc:
            return ToolResult(False, f"edit: {exc}")
        snapshot = tool_state["snapshot"]
        ref_map = view_mod.present(
            snapshot, view_mod.line_number, view_mod.cat_n
        ).reference_map
        n = len(snapshot.blocks)
        if not (1 <= start <= end <= n):
            return ToolResult(
                False, f"edit: line range {start}:{end} out of range (1..{n})"
            )
        keys = [ref_map.key_of(str(i)) for i in range(start, end + 1)]
        anchor: str = ref_map.key_of(str(start - 1)) if start > 1 else ir.HEAD
        # 降解：Remove 覆盖块 + 逐行 Append（批次内新 key 按 b{cursor+i} 可预期）
        ops: list[ir.Op] = [ir.Remove(key) for key in keys]
        lines = text.split("\n")
        trailing_nl = snapshot.blocks[-1].content.endswith("\n")
        cursor = snapshot.key_cursor
        for i, line in enumerate(lines):
            content = line + "\n"
            if i == len(lines) - 1 and end == n and not trailing_nl:
                content = line  # 替换到文末且原文末行无换行：保持无换行
            at = anchor if i == 0 else f"b{cursor + i - 1}"
            ops.append(ir.Append(draft_content=content, draft_attrs={}, at=at))
        try:
            new_snapshot = ir.apply(snapshot, tuple(ops))
        except ir.OpError as exc:
            return ToolResult(False, f"edit failed: {exc}")
        tool_state["snapshot"] = new_snapshot  # 内存推进，轮末 flush 落盘
        # 回显被改区域（全局行号，上下文各 2 行）
        blocks = new_snapshot.blocks
        added = len(lines)
        lo = max(1, start - 2)
        hi = min(len(blocks), start - 1 + added + 2)
        shown = "".join(
            view_mod.cat_n(str(i), blocks[i - 1].content) for i in range(lo, hi + 1)
        )
        return ToolResult(True, f"edit applied.\n{shown}")


def _parse_edit_args(args_text: str) -> tuple[int, int, str]:
    """解析 `start, end, "text"`（受控解析：两个整数 + 一个 JSON 字符串）。"""
    try:
        parsed = json.loads(f"[{args_text}]")
    except json.JSONDecodeError as exc:
        raise ToolParseError(f"invalid JSON string: {exc.msg}") from exc
    match parsed:
        case [int(start), int(end), str(text)] if not isinstance(start, bool) and not isinstance(end, bool):
            return start, end, text
        case [*args] if len(args) != 3:
            raise ToolParseError("edit takes exactly 3 arguments")
        case [start, _, _] if not isinstance(start, int) or isinstance(start, bool):
            raise ToolParseError(f"expected integer argument, got {start!r}")
        case [_, end, _] if not isinstance(end, int) or isinstance(end, bool):
            raise ToolParseError(f"expected integer argument, got {end!r}")
        case [_, _, text]:
            raise ToolParseError(f"third argument must be a JSON string, got {text!r}")

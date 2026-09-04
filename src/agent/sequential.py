"""标准工具配置：rewrite_seq / patch_seq（逐单元顺序修复，一文档一场对话）。

对应 Docs/Design/09-tools.md「标准工具配置」节。

- 一个文档 = 一场多轮对话：每轮呈现一个单元（chunk），模型响应该单元的
  修复（rewrite = 重写文本；patch = fn patch），对话轮数 = 单元数。
- **无反馈口径**：模型每轮只看到下一个单元的呈现；工具结果与错误不回灌
  （对齐 rewrite「无多余返回信息」的口径）。parse 因此永不抛错——任何
  响应都视为该单元的提交；patch 的方言/应用错误在 invoke 内吞掉，该单元
  保留原文。分析走 replay 重 fold（磁带里有完整 patch 文本）。
- 终止：最后一个单元的 invoke 返回 ``ToolResult(finish=True)``。
- 每个单元只修复一次（单机会语义）。
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
import surface
import view as view_mod
from agent.assembly import format_input
from agent.patch import patch_clause
from agent.session import Session
from agent.standard import REWRITE_CLAUSE, extract_rewrite_text
from agent.toolset import ToolCall, ToolResult
from sourceio import SourceText

__all__ = [
    "RewriteSeqToolSet",
    "PatchSeqToolSet",
    "SweEditSeqToolSet",
    "FindReplaceSeqToolSet",
    "PatchGlobalSeqToolSet",
    "SweEditGlobalSeqToolSet",
    "FindReplaceGlobalSeqToolSet",
    "SEQ_REWRITE_CLAUSE",
    "SWE_EDIT_SEQ_CLAUSE",
    "FIND_REPLACE_SEQ_CLAUSE",
    "SWE_EDIT_GLOBAL_SEQ_CLAUSE",
    "FIND_REPLACE_GLOBAL_SEQ_CLAUSE",
]

DOC_SEPARATOR = "\n"
"""单元拼接分隔符（与数据集装载一致）。"""


def _split_units(text: str, boundaries: Any) -> tuple[str, ...]:
    """按 unit_boundaries（各单元起始偏移）切回单元；无则整体为单单元。

    单元间分隔符恒为数据集装载口径 DOC_SEPARATOR（"\n"）。
    """
    if not boundaries or not isinstance(boundaries, (list, tuple)) or len(boundaries) < 2:
        return (text,)
    units: list[str] = []
    for i, start in enumerate(boundaries):
        if i + 1 < len(boundaries):
            end = boundaries[i + 1] - len(DOC_SEPARATOR)
        else:
            end = len(text)
        units.append(text[start:end])
    return tuple(units)


SEQ_REWRITE_CLAUSE = """\
The text arrives one part at a time. Correct EACH part as it arrives, using the output format below.

""" + REWRITE_CLAUSE
"""rewrite_seq 的条款：逐部分顺序修复，输出格式与 rewrite 一致。"""


def _source(text: str) -> SourceText:
    return SourceText(text=text, encoding="utf-8", bom=b"")


class RewriteSeqToolSet:
    """逐单元顺序重写：每轮 submit 一个单元的重写文本（JSON 条款）。"""

    name = "rewrite_seq"
    uses_llm = True
    prompt_clause = SEQ_REWRITE_CLAUSE

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        return {"chunks": chunks, "outputs": [], "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return tool_state["chunks"][0]

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        # 无反馈口径：任何响应都视为该单元的提交，parse 永不抛错
        return (ToolCall("submit", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "submit":
            return ToolResult(False, f"unknown tool: {call.name}")
        tool_state["outputs"].append(extract_rewrite_text(call.args_text))
        tool_state["index"] += 1
        return self._advance(tool_state)

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        # 预算截断等早退场景：未处理的单元回退原文
        outputs = list(tool_state["outputs"]) + list(
            tool_state["chunks"][len(tool_state["outputs"]):]
        )
        return _source(DOC_SEPARATOR.join(outputs))

    # -- 内部 -------------------------------------------------------------

    def _advance(self, tool_state: dict) -> ToolResult:
        index = tool_state["index"]
        chunks = tool_state["chunks"]
        if index >= len(chunks):
            return ToolResult(True, "", finish=True)
        # 下一轮 user 消息 = 下一个单元的呈现（与首条同一包装口径）
        return ToolResult(
            True, format_input(chunks[index], tool_state["meta"])
        )


class PatchSeqToolSet:
    """逐单元顺序 patch：每个单元独立的 IR 会话（块 id 每单元重排）。"""

    name = "patch_seq"
    uses_llm = True

    def __init__(
        self,
        partition_kind: str = "lines",
        block_size: int = 400,
        *,
        apply_mode: str = surface.APPLY_ATOMIC,
        hidden_ops: frozenset[str] = frozenset(),
    ) -> None:
        if partition_kind not in ("lines", "chars"):
            raise ValueError(f"unknown partition: {partition_kind!r}")
        if apply_mode not in (surface.APPLY_ATOMIC, surface.APPLY_BEST_EFFORT):
            raise ValueError(f"unknown apply_mode: {apply_mode!r}")
        self._partition_kind = partition_kind
        self._block_size = block_size
        self._apply_mode = apply_mode
        self.prompt_clause = patch_clause(hidden_ops, sequential=True)

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        stores = []
        for i, chunk in enumerate(chunks):
            store = ir.Store(workdir / f"unit_{i}" / "session")
            source = sourceio.SourceText(text=chunk, encoding="utf-8", bom=b"")
            if self._partition_kind == "lines":
                result = partition.partition_lines(source)
            else:
                result = partition.partition_chars(source, self._block_size)
            ir.save(store, ir.birth(source, result))
            stores.append(store)
        return {"stores": stores, "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state["stores"][0])

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        # 无反馈口径：任何响应都视为该单元的 patch 提交，parse 永不抛错
        return (ToolCall("run_patch", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "run_patch":
            return ToolResult(False, f"unknown tool: {call.name}")
        store = tool_state["stores"][tool_state["index"]]
        try:
            surface.run_patch(
                store,
                call.args_text,
                view_mod.blockkey_as_is,
                view_mod.xml_ish,
                mode=self._apply_mode,
            )
        except (surface.ParseError, surface.SurfaceError):
            pass  # 单机会语义：该单元保留原文；错误不回灌（口径对齐 rewrite_seq）
        tool_state["index"] += 1
        index = tool_state["index"]
        stores = tool_state["stores"]
        if index >= len(stores):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(stores[index]), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        texts = [
            reconstruction.reconstruct(ir.load(store, ir.current(store))).text
            for store in tool_state["stores"]
        ]
        return _source(DOC_SEPARATOR.join(texts))

    # -- 内部 -------------------------------------------------------------

    def _render(self, store: ir.Store) -> str:
        snapshot = ir.load(store, ir.current(store))
        agent_view = view_mod.present(
            snapshot, view_mod.blockkey_as_is, view_mod.xml_ish
        )
        return agent_view.payload


_HEREDOC_RE = re.compile(
    r"edit\s+(?:(?P<target>\w+)\s+)?(?P<start>\d+):(?P<end>\d+)\s*<<\s*(?P<delim>\S+)\r?\n(?P<body>.*?)\r?\n(?P=delim)",
    re.DOTALL,
)
_CALL_EDIT_RE = re.compile(
    r"edit\s*\(\s*(?:(?P<target>[A-Za-z0-9_]+)\s*,\s*)?(?P<start>\d+)\s*,\s*(?P<end>\d+)\s*,\s*(?P<text>.*?)\s*\)",
    re.DOTALL,
)


def _extract_swe_edits(text: str) -> list[tuple[str | None, int, int, str]]:
    """提取文本中的 edit 命令列表：(target, start, end, body)。"""
    results: list[tuple[str | None, int, int, str]] = []
    for m in _HEREDOC_RE.finditer(text):
        target = m.group("target")
        start = int(m.group("start"))
        end = int(m.group("end"))
        body = m.group("body")
        results.append((target, start, end, body))
    if not results:
        for m in _CALL_EDIT_RE.finditer(text):
            target = m.group("target")
            start = int(m.group("start"))
            end = int(m.group("end"))
            raw_text = m.group("text").strip()
            try:
                body = json.loads(raw_text)
            except Exception:
                body = raw_text.strip('"\'')
            results.append((target, start, end, body))
    return results


def _apply_swe_edit(store: ir.Store, start: int, end: int, text: str) -> None:
    snapshot = ir.load(store, ir.current(store))
    n = len(snapshot.blocks)
    if not (1 <= start <= end <= n):
        return
    ref_map = view_mod.present(
        snapshot, view_mod.line_number, view_mod.cat_n
    ).reference_map
    keys = [ref_map.key_of(str(i)) for i in range(start, end + 1)]
    anchor: str = ref_map.key_of(str(start - 1)) if start > 1 else ir.HEAD
    ops: list[ir.Op] = [ir.Remove(key) for key in keys]
    lines = text.split("\n")
    trailing_nl = snapshot.blocks[-1].content.endswith("\n")
    cursor = snapshot.key_cursor
    for i, line in enumerate(lines):
        content = line + "\n"
        if i == len(lines) - 1 and end == n and not trailing_nl:
            content = line
        at = anchor if i == 0 else f"b{cursor + i - 1}"
        ops.append(ir.Append(draft_content=content, draft_attrs={}, at=at))
    try:
        new_snapshot = ir.apply(snapshot, tuple(ops))
        ir.save(store, new_snapshot)
    except ir.OpError:
        pass


_FIND_REPLACE_CALL_RE = re.compile(
    r"find_replace\s*\(\s*(.*?)\s*\)", re.DOTALL
)


def _extract_find_replace_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for m in _FIND_REPLACE_CALL_RE.finditer(text):
        args_text = m.group(1)
        try:
            parsed = json.loads(f"[{args_text}]")
            if (
                len(parsed) == 2
                and isinstance(parsed[0], str)
                and isinstance(parsed[1], str)
            ):
                pairs.append((parsed[0], parsed[1]))
        except Exception:
            pass
    return pairs


SWE_EDIT_SEQ_CLAUSE = """\
The text arrives one part at a time. For EACH part as it arrives, you can edit lines within that part.
Lines are numbered starting from 1 for each part.
To edit lines, use:
edit <start_line>:<end_line> << end_of_edit
<replacement text>
end_of_edit

Output ONLY the edit command. If no correction is needed, output done() or leave empty.
"""


class SweEditSeqToolSet:
    """逐单元局部行号编辑（2.a：Scope-Constrained，单机会，每 chunk 行号独立从 1 编）。"""

    name = "swe_edit_seq"
    uses_llm = True
    prompt_clause = SWE_EDIT_SEQ_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        stores = []
        for i, chunk in enumerate(chunks):
            store = ir.Store(workdir / f"unit_{i}" / "session")
            source = sourceio.SourceText(text=chunk, encoding="utf-8", bom=b"")
            ir.save(store, ir.birth(source, partition.partition_lines(source)))
            stores.append(store)
        return {"stores": stores, "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state, 0)

    def _render(self, tool_state: dict, idx: int) -> str:
        store = tool_state["stores"][idx]
        snapshot = ir.load(store, ir.current(store))
        return view_mod.present(snapshot, view_mod.line_number, view_mod.cat_n).payload

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        return (ToolCall("edit", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "edit":
            return ToolResult(False, f"unknown tool: {call.name}")
        idx = tool_state["index"]
        edits = _extract_swe_edits(call.args_text)
        store = tool_state["stores"][idx]
        for _, start, end, body in edits:
            _apply_swe_edit(store, start, end, body)
        tool_state["index"] += 1
        index = tool_state["index"]
        stores = tool_state["stores"]
        if index >= len(stores):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(tool_state, index), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        texts = [
            reconstruction.reconstruct(ir.load(s, ir.current(s))).text
            for s in tool_state["stores"]
        ]
        return _source(DOC_SEPARATOR.join(texts))


FIND_REPLACE_SEQ_CLAUSE = """\
The text arrives one part at a time. For EACH part as it arrives, correct errors using:
find_replace("old", "new")

Output ONLY the calls. If no correction is needed, output done() or leave empty.
"""


class FindReplaceSeqToolSet:
    """逐单元局部字符串替换（2.a：Scope-Constrained，仅在当前 chunk 生效）。"""

    name = "find_replace_seq"
    uses_llm = True
    prompt_clause = FIND_REPLACE_SEQ_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        return {"chunks": list(chunks), "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return tool_state["chunks"][0]

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        return (ToolCall("find_replace", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "find_replace":
            return ToolResult(False, f"unknown tool: {call.name}")
        idx = tool_state["index"]
        pairs = _extract_find_replace_pairs(call.args_text)
        current = tool_state["chunks"][idx]
        for old, new in pairs:
            current = current.replace(old, new)
        tool_state["chunks"][idx] = current
        tool_state["index"] += 1
        index = tool_state["index"]
        chunks = tool_state["chunks"]
        if index >= len(chunks):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(chunks[index], tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return _source(DOC_SEPARATOR.join(tool_state["chunks"]))


class PatchGlobalSeqToolSet:
    """逐单元流式输入 + 全局回溯 patch（2.b：前缀块 ID 如 c0:b1，跨 chunk 路由修复）。"""

    name = "patch_global_seq"
    uses_llm = True

    def __init__(
        self,
        partition_kind: str = "lines",
        block_size: int = 400,
        *,
        apply_mode: str = surface.APPLY_BEST_EFFORT,
        hidden_ops: frozenset[str] = frozenset(),
    ) -> None:
        if partition_kind not in ("lines", "chars"):
            raise ValueError(f"unknown partition: {partition_kind!r}")
        if apply_mode not in (surface.APPLY_ATOMIC, surface.APPLY_BEST_EFFORT):
            raise ValueError(f"unknown apply_mode: {apply_mode!r}")
        self._partition_kind = partition_kind
        self._block_size = block_size
        self._apply_mode = apply_mode
        self.prompt_clause = patch_clause(hidden_ops, sequential=True)

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        stores = []
        for i, chunk in enumerate(chunks):
            store = ir.Store(workdir / f"unit_{i}" / "session")
            source = sourceio.SourceText(text=chunk, encoding="utf-8", bom=b"")
            if self._partition_kind == "lines":
                result = partition.partition_lines(source)
            else:
                result = partition.partition_chars(source, self._block_size)
            ir.save(store, ir.birth(source, result))
            stores.append(store)
        return {"stores": stores, "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state, 0)

    def _render(self, tool_state: dict, idx: int) -> str:
        store = tool_state["stores"][idx]
        snapshot = ir.load(store, ir.current(store))
        agent_view = view_mod.present_file(
            snapshot, f"chunk_{idx}", prefix=f"c{idx}"
        )
        return agent_view.payload

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        return (ToolCall("run_patch", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "run_patch":
            return ToolResult(False, f"unknown tool: {call.name}")
        if call.args_text.strip():
            try:
                surface_ops = surface.parse(call.args_text)
            except surface.ParseError:
                surface_ops = ()
            by_chunk: dict[int, list[surface.SurfaceOp]] = {}
            for op in surface_ops:
                # 按 op 的主 id 路由（surface ops 的字段：id / anchor / a）
                target_id = None
                for attr in ("id", "anchor", "a"):
                    v = getattr(op, attr, None)
                    if isinstance(v, str):
                        target_id = v
                        break
                chunk_idx = tool_state["index"]
                if target_id and ":" in target_id:
                    p = target_id.split(":", 1)[0]
                    if p.startswith("c") and p[1:].isdigit():
                        chunk_idx = int(p[1:])
                if 0 <= chunk_idx < len(tool_state["stores"]):
                    by_chunk.setdefault(chunk_idx, []).append(op)
            for k, ops in by_chunk.items():
                store = tool_state["stores"][k]
                snapshot = ir.load(store, ir.current(store))
                strategy = view_mod.prefixed_blockkey(f"c{k}")
                ref_map = view_mod.present(
                    snapshot, strategy, view_mod.xml_ish
                ).reference_map
                try:
                    entries = surface.degrade(tuple(ops), ref_map, snapshot)
                    core_ops = tuple(c_op for c_op, _ in entries)
                    new_snapshot = ir.apply(snapshot, core_ops)
                    ir.save(store, new_snapshot)
                except (surface.SurfaceError, ir.OpError):
                    pass
        tool_state["index"] += 1
        index = tool_state["index"]
        stores = tool_state["stores"]
        if index >= len(stores):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(tool_state, index), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        texts = [
            reconstruction.reconstruct(ir.load(store, ir.current(store))).text
            for store in tool_state["stores"]
        ]
        return _source(DOC_SEPARATOR.join(texts))


SWE_EDIT_GLOBAL_SEQ_CLAUSE = """\
The text arrives one file/chunk at a time (indicated by `--- [File: chunk_N] ---`).
You can edit any chunk presented so far by specifying the file name:
edit <chunk_name> <start_line>:<end_line> << end_of_edit
<replacement text>
end_of_edit

Output ONLY the edit commands. If no correction is needed, output done() or leave empty.
"""


class SweEditGlobalSeqToolSet:
    """逐单元流式输入 + 全局回溯行号编辑（2.b：支持指定目标 chunk 跨文件回溯）。"""

    name = "swe_edit_global_seq"
    uses_llm = True
    prompt_clause = SWE_EDIT_GLOBAL_SEQ_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        stores = []
        for i, chunk in enumerate(chunks):
            store = ir.Store(workdir / f"unit_{i}" / "session")
            source = sourceio.SourceText(text=chunk, encoding="utf-8", bom=b"")
            ir.save(store, ir.birth(source, partition.partition_lines(source)))
            stores.append(store)
        return {"stores": stores, "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state, 0)

    def _render(self, tool_state: dict, idx: int) -> str:
        store = tool_state["stores"][idx]
        snapshot = ir.load(store, ir.current(store))
        header = f"--- [File: chunk_{idx}] ---\n"
        view = view_mod.present(snapshot, view_mod.line_number, view_mod.cat_n).payload
        return header + view

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        return (ToolCall("edit", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "edit":
            return ToolResult(False, f"unknown tool: {call.name}")
        edits = _extract_swe_edits(call.args_text)
        stores = tool_state["stores"]
        for target, start, end, body in edits:
            target_idx = tool_state["index"]
            if target:
                if target.startswith("chunk_") and target[6:].isdigit():
                    target_idx = int(target[6:])
                elif target.isdigit():
                    target_idx = int(target)
            if 0 <= target_idx < len(stores):
                _apply_swe_edit(stores[target_idx], start, end, body)
        tool_state["index"] += 1
        index = tool_state["index"]
        if index >= len(stores):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(tool_state, index), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        texts = [
            reconstruction.reconstruct(ir.load(s, ir.current(s))).text
            for s in tool_state["stores"]
        ]
        return _source(DOC_SEPARATOR.join(texts))


FIND_REPLACE_GLOBAL_SEQ_CLAUSE = """\
The text arrives one file/chunk at a time (indicated by `--- [File: chunk_N] ---`).
You can replace text across any chunks presented so far:
find_replace("old", "new")

Output ONLY the calls. If no correction is needed, output done() or leave empty.
"""


class FindReplaceGlobalSeqToolSet:
    """逐单元流式输入 + 全局回溯字符串替换（2.b：替换作用于所有已呈现 chunk）。"""

    name = "find_replace_global_seq"
    uses_llm = True
    prompt_clause = FIND_REPLACE_GLOBAL_SEQ_CLAUSE

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        return {"chunks": list(chunks), "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state, 0)

    def _render(self, tool_state: dict, idx: int) -> str:
        header = f"--- [File: chunk_{idx}] ---\n"
        return header + tool_state["chunks"][idx]

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        return (ToolCall("find_replace", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "find_replace":
            return ToolResult(False, f"unknown tool: {call.name}")
        pairs = _extract_find_replace_pairs(call.args_text)
        for old, new in pairs:
            for i in range(tool_state["index"] + 1):
                tool_state["chunks"][i] = tool_state["chunks"][i].replace(old, new)
        tool_state["index"] += 1
        index = tool_state["index"]
        chunks = tool_state["chunks"]
        if index >= len(chunks):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(tool_state, index), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return _source(DOC_SEPARATOR.join(tool_state["chunks"]))

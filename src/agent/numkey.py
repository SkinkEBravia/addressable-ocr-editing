"""标准工具配置：num-key 视图系（实验「锚与按锚聚焦」的四个臂，plan/neo_experiment.md）。

- 全部 IR-backed：partition_lines + birth；num-key = BlockKey 的序号部分
  （``b12`` -> ``"12"``，view 策略 ``numkey``）。BlockKey 由分配器取号、
  编辑（SetContent/Remove）不复用既有 key —— 这是「num-key 稳定、不重排」
  承诺的物理基础（与位置性的 swe_edit 行号相对）。
- 五个 num-key 臂共享同一段 view description（NUMKEY_VIEW_CLAUSE），差异只在
  tool prompt 与是否附加注意力控制条款（ATTENTION_CLAUSE）；
  unstable 臂单独用 LINE_NUMBER_VIEW_CLAUSE（位置性语义如实披露）。
  全部臂 prompt_clause 末尾追加同一段 1-shot 告知（ONE_SHOT_NOTICE_*，
  实验组口径：1 doc per session, 1 shot）。

    | 臂 | 工具 | 注意力条款 |
    |---|---|---|
    | rewrite_numkey       | 无（单轮全文重写）              | 无 |
    | find_replace_numkey  | find_replace(path, old, new)    | 无 |
    | find_replace_blocked | 同上（同一实现）                | 有 |
    | patch_find_replace   | find_replace(path, key, old, new) | 有 |
    | patch_find_replace_noatt | 同 patch_find_replace（同一实现） | 无 |
    | patch_find_replace_unstable | 同 patch_find_replace（key 为位置性行号，编辑后重排） | 有 |

- patch_find_replace 只允许 find_replace 一种编辑操作：清单外操作在
  **parse 层**即拒绝（方言只认 read / find_replace / done），不是在提示词里
  隐去——与 patch_replace 的 allowed_ops 同一原则（提示词与拦截同源）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import ir
import partition
import reconstruction
import sourceio
import view as view_mod
from agent.session import Session
from agent.standard import (
    FIND_REPLACE_ANTHROPIC_CLAUSE,
    ONE_SHOT_NOTICE_REWRITE,
    ONE_SHOT_NOTICE_TOOLS,
    PATH_NAME,
    REWRITE_CLAUSE,
    _parse_path_and_rest,
    _parse_two_strings,
    _unknown_path,
    extract_rewrite_text,
)
from agent.toolset import DONE, Done, ToolCall, ToolParseError, ToolResult
from sourceio import SourceText

__all__ = [
    "RewriteNumkeyToolSet",
    "FindReplaceNumkeyToolSet",
    "FindReplaceBlockedToolSet",
    "PatchFindReplaceToolSet",
    "PatchFindReplaceNoattToolSet",
    "PatchFindReplaceUnstableToolSet",
    "NUMKEY_VIEW_CLAUSE",
    "ATTENTION_CLAUSE",
    "FIND_REPLACE_NUMKEY_CLAUSE",
    "PATCH_FIND_REPLACE_CLAUSE",
    "LINE_NUMBER_VIEW_CLAUSE",
    "PATCH_FIND_REPLACE_LINES_CLAUSE",
]

# ---------------------------------------------------------------------------
# 提示词条款（与 plan/neo_experiment.md appendix 逐字一致；改动需同步）
# ---------------------------------------------------------------------------

NUMKEY_VIEW_CLAUSE = """\
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output."""

ATTENTION_CLAUSE = """\
Work in two passes before you emit any call.

Pass 1 — one block at a time. Go through the blocks in order and note what looks wrong inside each block on its own. Do not decide on any fix yet.

Pass 2 — across blocks. Now read the whole text. The same word, name or spelling usually appears more than once: where one occurrence is clean, it tells you how a garbled one elsewhere should read. Settle the notes from pass 1 with that evidence, and drop any you can no longer justify.

Then emit your calls."""

# num-key 视图下 read() 返回带 num-key 的当前文本，条款如实告知（其余逐字同
# FIND_REPLACE_ANTHROPIC_CLAUSE，单源派生防止漂移）。
FIND_REPLACE_NUMKEY_CLAUSE = FIND_REPLACE_ANTHROPIC_CLAUSE.replace(
    "return the current text of `path`",
    "return the current text of `path` with its num-keys",
)

PATCH_FIND_REPLACE_CLAUSE = """\
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
- find_replace(path, key, "old", "new") — replace "old" with "new" inside the block with num-key `key` in `path`. "old" must be copied VERBATIM from that block and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the block, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

# ---------------------------------------------------------------------------
# 方言解析（read / find_replace / done，一行一个调用；与 standard.py 同款）
# ---------------------------------------------------------------------------

_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\Z", re.DOTALL)
_KNOWN = ("read", "find_replace")

_KEY_ARG_RE = re.compile(r'\s*(?:"(\d+)"|(\d+))\s*,\s*(.*)\Z', re.DOTALL)


def _parse_call_lines(text: str) -> "tuple[ToolCall, ...] | Done":
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
            raise ToolParseError(f"line {lineno}: done() 只能出现在消息最后一行")
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


def _parse_key_and_rest(args_text: str) -> tuple[int, str]:
    """拆分 num-key 参数（裸整数或 JSON 字符串）与剩余参数文本。"""
    m = _KEY_ARG_RE.match(args_text)
    if m is None:
        raise ToolParseError("expected num-key (integer) as second argument")
    return int(m.group(1) or m.group(2)), m.group(3)


# ---------------------------------------------------------------------------
# 基座：IR store + numkey 视图
# ---------------------------------------------------------------------------


class _NumkeyDocBase:
    """IR-backed 文档状态 + 编号视图（num-key 稳定性的物理基础）。

    ``_STRATEGY`` 决定编号语义：``numkey``（稳定，BlockKey 序号）是默认；
    ``line_number``（位置性，行号）用于 unstable 变体。
    （staticmethod 包装：函数作类属性否则会被绑定成方法。）

    落盘节奏：**轮末 flush**——轮内编辑只推进内存快照
    （``tool_state["snapshot"]``），一轮执行完由 loop 调 ``flush`` 一次性
    落盘（逐编辑 save 在挂载盘上是千次级文件操作/编辑，实测拖垮大批量
    调用）。快照粒度 = 轮；逐调用审计由磁带的 calls/results 承担。
    """

    uses_llm = True
    _STRATEGY = staticmethod(view_mod.numkey)

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
        snapshot = self._snapshot(tool_state)
        return view_mod.present_file(
            snapshot,
            PATH_NAME,
            annotator=view_mod.cat_n,
            strategy=self._STRATEGY,
            label="Text",
        ).payload

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        return reconstruction.reconstruct(self._snapshot(tool_state))

    # -- 内部 -------------------------------------------------------------

    def _snapshot(self, tool_state: dict) -> ir.DocumentSnapshot:
        return tool_state["snapshot"]  # 内存快照（轮末 flush 才落盘）

    def _view_payload(self, tool_state: dict) -> str:
        """read() 的返回：带编号的当前文本（不含 path 抬头——抬头是
        寻址元数据，只在首条 user 消息的呈现里出现一次）。"""
        return view_mod.present(
            self._snapshot(tool_state), self._STRATEGY, view_mod.cat_n
        ).payload

    def _read(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            path, rest = _parse_path_and_rest(call.args_text)
        except ToolParseError as exc:
            return ToolResult(False, f"read: {exc}")
        if rest:
            return ToolResult(False, "read: takes exactly 1 argument (path)")
        if path != PATH_NAME:
            return ToolResult(False, f"read: {_unknown_path(path)}")
        return ToolResult(True, self._view_payload(tool_state))


# ---------------------------------------------------------------------------
# 臂 1：rewrite_numkey（num-key 视图 + 单轮全文重写）
# ---------------------------------------------------------------------------


class RewriteNumkeyToolSet(_NumkeyDocBase):
    """rewrite 的 num-key 视图变体：输入带 num-key（key 不是文本的一部分），
    条款与输出解析不变（单轮全文重写，JSON 条款）。"""

    name = "rewrite_numkey"
    prompt_clause = NUMKEY_VIEW_CLAUSE + "\n\n" + REWRITE_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_REWRITE

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        # 空工具集：任何非空响应都直接完成（空响应已被 08 的 client 层拦截）
        if not text.strip():
            raise ToolParseError("empty response")
        return DONE

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        text = session.turns[-1].completion.text if session.turns else ""
        return SourceText(
            text=extract_rewrite_text(text), encoding="utf-8", bom=b""
        )


# ---------------------------------------------------------------------------
# 臂 2/3：find_replace_numkey / find_replace_blocked（path 内唯一匹配）
# ---------------------------------------------------------------------------


class FindReplaceNumkeyToolSet(_NumkeyDocBase):
    """num-key 视图 + find_replace(path, "old", "new")（path 内唯一匹配）。

    工具语义与 find_replace_anthropic_style 完全一致；唯一差别是输入呈现
    与 read() 带 num-key（key 对工具不可用，只「看得见」）。
    """

    name = "find_replace_numkey"
    prompt_clause = (
        NUMKEY_VIEW_CLAUSE + "\n\n" + FIND_REPLACE_NUMKEY_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_TOOLS
    )

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        return _parse_call_lines(text)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name == "done":
            return ToolResult(True, "", finish=True)
        if call.name == "read":
            return self._read(call, tool_state)
        if call.name == "find_replace":
            return self._find_replace(call, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    # -- 内部 -------------------------------------------------------------

    def _find_replace(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            path, rest = _parse_path_and_rest(call.args_text)
            old, new = _parse_two_strings(rest)
        except ToolParseError as exc:
            return ToolResult(False, f"find_replace: {exc}")
        if path != PATH_NAME:
            return ToolResult(False, f"find_replace: {_unknown_path(path)}")
        snapshot = self._snapshot(tool_state)
        text = reconstruction.reconstruct(snapshot).text
        count = text.count(old)
        if count == 0:
            return ToolResult(False, f"PATTERN_NOT_FOUND: {old!r} does not occur")
        if count > 1:
            return ToolResult(
                False,
                f"Found {count} matches for {old!r}. "
                "Please provide more context to make a unique match.",
            )
        return self._apply_unique(tool_state, snapshot, text, old, new)

    def _apply_unique(
        self, tool_state: dict, snapshot: ir.DocumentSnapshot,
        text: str, old: str, new: str,
    ) -> ToolResult:
        """把全文内唯一的 old 出现处换成 new（可跨块），降解为 SetContent(+Remove)。

        跨块时并入首个涉及块、移除其余涉及块——既有块 key 不变更、不复用，
        num-key 稳定性不受影响。
        """
        start = text.index(old)
        end = start + len(old)
        involved: list[tuple[ir.Block, int]] = []
        offset = 0
        for block in snapshot.blocks:
            block_end = offset + len(block.content)
            if block_end > start and offset < end:
                involved.append((block, offset))
            offset = block_end
        first, first_off = involved[0]
        last, last_off = involved[-1]
        merged = first.content[: start - first_off] + new + last.content[end - last_off:]
        ops: list[ir.Op] = [ir.SetContent(first.key, merged)]
        ops.extend(ir.Remove(block.key) for block, _ in involved[1:])
        try:
            new_snapshot = ir.apply(snapshot, tuple(ops))
        except ir.OpError as exc:
            return ToolResult(False, f"edit failed: {exc}")
        tool_state["snapshot"] = new_snapshot  # 内存推进，轮末 flush 落盘
        return ToolResult(True, "replaced 1 occurrence")


class FindReplaceBlockedToolSet(FindReplaceNumkeyToolSet):
    """find_replace_numkey + 注意力控制条款（先逐块、再跨块两遍）。

    与 find_replace_numkey 共用同一工具实现，只有 prompt_clause 不同——
    这一对隔离的变量就是提示词。
    """

    name = "find_replace_blocked"
    prompt_clause = (
        NUMKEY_VIEW_CLAUSE + "\n\n" + FIND_REPLACE_NUMKEY_CLAUSE + "\n\n"
        + ATTENTION_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_TOOLS
    )


# ---------------------------------------------------------------------------
# 臂 4：patch_find_replace（num-key 定位 + 块内唯一匹配）
# ---------------------------------------------------------------------------


class PatchFindReplaceToolSet(_NumkeyDocBase):
    """num-key 视图 + find_replace(path, key, "old", "new")：唯一性只在
    num-key 指定的块内判定。清单外操作在 parse 层拒绝（方言只认
    read / find_replace / done）。
    """

    name = "patch_find_replace"
    prompt_clause = (
        NUMKEY_VIEW_CLAUSE + "\n\n" + PATCH_FIND_REPLACE_CLAUSE + "\n\n"
        + ATTENTION_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_TOOLS
    )

    _KEY_NOUN = "block"

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        return _parse_call_lines(text)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name == "done":
            return ToolResult(True, "", finish=True)
        if call.name == "read":
            return self._read(call, tool_state)
        if call.name == "find_replace":
            return self._find_replace(call, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    # -- 内部 -------------------------------------------------------------

    def _after_edit(self, tool_state: dict) -> None:
        """编辑后的钩子：稳定臂无操作；unstable 变体重排编号。"""

    def _find_replace(self, call: ToolCall, tool_state: dict) -> ToolResult:
        try:
            path, rest = _parse_path_and_rest(call.args_text)
            key, rest = _parse_key_and_rest(rest)
            old, new = _parse_two_strings(rest)
        except ToolParseError as exc:
            return ToolResult(False, f"find_replace: {exc}")
        if path != PATH_NAME:
            return ToolResult(False, f"find_replace: {_unknown_path(path)}")
        snapshot = self._snapshot(tool_state)
        ref_map = view_mod.present(
            snapshot, self._STRATEGY, view_mod.cat_n
        ).reference_map
        noun = self._KEY_NOUN
        try:
            block_key = ref_map.key_of(str(key))
        except KeyError:
            return ToolResult(False, f"find_replace: no {noun} numbered {key}")
        block = next(b for b in snapshot.blocks if b.key == block_key)
        count = block.content.count(old)
        if count == 0:
            return ToolResult(
                False, f"PATTERN_NOT_FOUND: {old!r} does not occur in {noun} {key}"
            )
        if count > 1:
            return ToolResult(
                False,
                f"Found {count} matches for {old!r} in {noun} {key}. "
                "Please provide more context to make a unique match.",
            )
        new_content = block.content.replace(old, new)
        try:
            new_snapshot = ir.apply(
                snapshot, (ir.SetContent(block_key, new_content),)
            )
        except ir.OpError as exc:
            return ToolResult(False, f"edit failed: {exc}")
        tool_state["snapshot"] = new_snapshot  # 内存推进，轮末 flush 落盘
        self._after_edit(tool_state)
        # 回显被改位置（同一 (strategy, annotator)；被改位置的起始编号不变）
        annotated = view_mod.cat_n(str(key), new_content).rstrip("\n")
        return ToolResult(True, f"replaced 1 occurrence in {noun} {key}.\n{annotated}")


# ---------------------------------------------------------------------------
# 臂 5/6：patch_find_replace 的两个对照变体
# ---------------------------------------------------------------------------


class PatchFindReplaceNoattToolSet(PatchFindReplaceToolSet):
    """patch_find_replace 的无注意力条款变体：同一实现，仅 prompt_clause
    不含 ATTENTION_CLAUSE。与 find_replace_numkey / patch_find_replace
    配对成「注意力控制 × 用 key 定位」的 2×2。"""

    name = "patch_find_replace_noatt"
    prompt_clause = (
        NUMKEY_VIEW_CLAUSE + "\n\n" + PATCH_FIND_REPLACE_CLAUSE + "\n\n"
        + ONE_SHOT_NOTICE_TOOLS
    )


LINE_NUMBER_VIEW_CLAUSE = """\
Each line of the text is prefixed by a line number:

  <line number>: <line content>

Line numbers are POSITIONAL, not stable identifiers: whenever one of your edits adds or removes lines, the lines below it are renumbered. A number you saw before such an edit may point to a DIFFERENT line after it — within your batch of calls, later calls see the numbering shifted by your earlier edits. The numbers are not part of the text; never include them in what you output."""
"""位置性行号的 view description（unstable 臂）：与 NUMKEY_VIEW_CLAUSE 逐段对照，
唯一差别是稳定性语义的披露方向。"""

PATCH_FIND_REPLACE_LINES_CLAUSE = """\
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its line numbers
- find_replace(path, line, "old", "new") — replace "old" with "new" inside the line numbered `line` in `path`. "old" must be copied VERBATIM from that line and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the line, then try again. `line` refers to the CURRENT numbering, which shifts when earlier calls add or remove lines
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""
"""行号版 find_replace 条款：与 PATCH_FIND_REPLACE_CLAUSE 逐行对照，
差异 = num-key→line 的措辞 + 「当前编号会漂移」的披露。"""


class PatchFindReplaceUnstableToolSet(PatchFindReplaceToolSet):
    """patch_find_replace 的位置性 key 变体：真正的行号。

    外观与 patch_find_replace 完全相同（``N: 内容`` 视图、同一
    find_replace(path, key, old, new) 签名），唯一差别是稳定性：
    每次编辑后全文重新 partition + re-birth，编号按位置重排——
    行数变化的编辑使其后的编号漂移（1-shot 下同批后续调用的 key 即指错）。
    """

    name = "patch_find_replace_unstable"
    prompt_clause = (
        LINE_NUMBER_VIEW_CLAUSE + "\n\n" + PATCH_FIND_REPLACE_LINES_CLAUSE + "\n\n"
        + ATTENTION_CLAUSE + "\n\n" + ONE_SHOT_NOTICE_TOOLS
    )

    _STRATEGY = staticmethod(view_mod.line_number)
    _KEY_NOUN = "line"

    def _after_edit(self, tool_state: dict) -> None:
        # 位置性 key：编辑后全文重 partition + re-birth，编号按位置重排
        # （纯内存操作；落盘在轮末 flush）
        text = reconstruction.reconstruct(tool_state["snapshot"]).text
        source = sourceio.SourceText(text=text, encoding="utf-8", bom=b"")
        tool_state["snapshot"] = ir.birth(source, partition.partition_lines(source))

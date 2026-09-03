"""标准工具配置：patch（本系统 IR 操作面，fn 方言）。

对应 Docs/Design/09-tools.md「标准工具配置」节；操作面见 07-agent-api.md。

- 只经本系统公开接口（05/06/07）使用 IR，不 import 内部。
- agent 对块的定位一律用 AgentBlockId；BlockKey 不出现在对话中
  （默认策略 blockkey-as-is 下两者同形，但语义上是 Agent 侧 id）。
- 方言：assistant 消息整体即一段 fn patch；``done()`` 单独一行 = Done；
  ``view()`` 单独一行 = 重新拉取当前视图。
- IR store 按 workdir 持久（工具集自管的持久状态，不进磁带）；
  磁带只存 calls/results，replay 重 fold 即重建。
- 应用策略可替换：``apply_mode="atomic"``（默认，07 原语义）/
  ``"best_effort"``（逐条应用，失败 op 跳过并在 feedback 中回报）。
- 提示词条款的操作清单可裁剪：``hidden_ops`` 隐去指定操作
  （OCR 修复里 append/merge 无意义——内容追加与插新块等效）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ir
import partition
import reconstruction
import sourceio
import surface
import view as view_mod
from agent.session import Session
from agent.toolset import DONE, Done, ToolCall, ToolParseError, ToolResult
from sourceio import SourceText

__all__ = ["PatchToolSet", "PATCH_CLAUSE", "patch_clause"]

_CLAUSE_HEAD = """\
The text is shown as an annotated view in which each block is marked as:

<x id="bN"\\>
block content (verbatim, unescaped)
</x>

(the "\\>" in the opening tag is intentionally not well-formed XML.)

Do NOT rewrite the whole text. Express your corrections as a patch in the fn dialect: one function call per line, using these operations:"""

_OP_BULLETS = {
    "replace": '- replace(id, "old", "new") — replace every occurrence of "old" inside block id with "new". PREFERRED for sparse errors: fix only the wrong fragment and leave the rest of the block untouched. Rules: "old" must be copied VERBATIM from the block (if it does not occur exactly, the patch fails); every occurrence of "old" in the block will change, so keep "old" as SHORT as possible while still unambiguous — every character you quote costs output tokens',
    "set_content": '- set_content(id, "text") — replace the whole content of block id; use only when most of the block changes',
    "set_attrs": '- set_attrs(id, {...}) — replace the attrs object of block id (rarely needed)',
    "append": '- append(anchor, "text") — insert a new block after block anchor (anchor may be HEAD for the document start); optional third argument for attrs',
    "remove": "- remove(id) — remove block id",
    "move": "- move(id, anchor) — move block id to after anchor",
    "merge": "- merge(a, b) — append b's content to a and remove b",
}

_CLAUSE_TAIL = """\
ids must be the ids shown in the annotations (or HEAD, only as an anchor); bare ids and quoted ids are equivalent (`b1` and "b1" both work). Strings and attrs objects use JSON syntax. Blank lines and lines starting with # are ignored.
After a successful patch you receive the affected blocks re-rendered; you may then emit another patch. When the text is fully corrected, output done() (alone, or as the last line after your patch).
To re-fetch the current annotated view, output a single line:
view()
Otherwise output ONLY the patch. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""

_CLAUSE_HEAD_SEQ = """\
The text arrives one part at a time. Each part is shown as an annotated view in which each block is marked as:

<x id="bN"\\>
block content (verbatim, unescaped)
</x>

(the "\\>" in the opening tag is intentionally not well-formed XML.)

Do NOT rewrite the whole text. Express your corrections as a patch in the fn dialect: one function call per line, using these operations:"""

_CLAUSE_TAIL_SEQ = """\
ids must be the ids shown in the annotations of the CURRENT part (or HEAD, only as an anchor); bare ids and quoted ids are equivalent (`b1` and "b1" both work). Strings and attrs objects use JSON syntax. Blank lines and lines starting with # are ignored.
After your patch, the NEXT part is shown; you will NOT receive any patch feedback. Output ONLY the patch for the current part. No explanation, no preamble, no markdown fences. If a part needs no correction, output a single comment line:
# no change"""

_OP_ORDER = ("replace", "set_content", "set_attrs", "append", "remove", "move", "merge")


def patch_clause(
    hidden_ops: frozenset[str] = frozenset(), *, sequential: bool = False
) -> str:
    """生成 patch 提示词条款；hidden_ops 中的操作从清单隐去。

    sequential=True：逐单元顺序模式（patch_seq）——无反馈，每部分一次机会。
    """
    unknown = set(hidden_ops) - set(_OP_ORDER)
    if unknown:
        raise ValueError(f"hidden_ops 含未知操作: {sorted(unknown)}")
    bullets = [_OP_BULLETS[op] for op in _OP_ORDER if op not in hidden_ops]
    head = _CLAUSE_HEAD_SEQ if sequential else _CLAUSE_HEAD
    tail = _CLAUSE_TAIL_SEQ if sequential else _CLAUSE_TAIL
    return "\n\n".join([head, "\n".join(bullets), tail])


PATCH_CLAUSE = patch_clause()
"""默认条款（全量操作清单）。"""


class PatchToolSet:
    """本系统块补丁工具集：view / run_patch 两个工具，fn 方言。"""

    name = "patch"
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
        self.prompt_clause = patch_clause(hidden_ops)

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        store = ir.Store(workdir / "session")
        source = sourceio.SourceText(text=task_input, encoding="utf-8", bom=b"")
        if self._partition_kind == "lines":
            result = partition.partition_lines(source)
        else:
            result = partition.partition_chars(source, self._block_size)
        snapshot = ir.birth(source, result)
        ir.save(store, snapshot)
        state: dict[str, Any] = {"store": store}
        state["payload"] = self._render(state)
        return state

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return tool_state["payload"]

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        stripped = text.strip()
        if not stripped:
            raise ToolParseError("empty response; emit a patch, view(), or done()")
        if stripped in ("done()", "done"):
            return DONE
        if stripped == "view()":
            return (ToolCall("view"),)
        # 末尾标记：patch 最后一行是 done()/done ⇒ 先应用 patch 再收束
        trailing_done = False
        lines = stripped.split("\n")
        if lines[-1].strip() in ("done()", "done"):
            trailing_done = True
            lines.pop()
            stripped = "\n".join(lines).strip()
        calls: list[ToolCall] = []
        if stripped:
            calls.append(ToolCall("run_patch", stripped))
        if trailing_done:
            calls.append(ToolCall("done"))
        return tuple(calls)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name == "done":
            return ToolResult(True, "", finish=True)
        if call.name == "view":
            payload = self._render(tool_state)
            tool_state["payload"] = payload
            return ToolResult(True, payload)
        if call.name == "run_patch":
            return self._apply_patch(call.args_text, tool_state)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        store: ir.Store = tool_state["store"]
        snapshot = ir.load(store, ir.current(store))
        return reconstruction.reconstruct(snapshot)

    # -- 内部 -------------------------------------------------------------

    def _render(self, tool_state: dict) -> str:
        store: ir.Store = tool_state["store"]
        snapshot = ir.load(store, ir.current(store))
        agent_view = view_mod.present(
            snapshot, view_mod.blockkey_as_is, view_mod.xml_ish
        )
        return agent_view.payload

    def _apply_patch(self, patch_text: str, tool_state: dict) -> ToolResult:
        store: ir.Store = tool_state["store"]
        try:
            result = surface.run_patch(
                store,
                patch_text,
                view_mod.blockkey_as_is,
                view_mod.xml_ish,
                mode=self._apply_mode,
            )
        except surface.ParseError as exc:
            return ToolResult(False, f"parse error at line {exc.line}: {exc.reason}")
        except surface.SurfaceError as exc:
            start, end = exc.position
            where = f"line {start}" if start == end else f"lines {start}-{end}"
            detail = f" ({exc.cause})" if exc.cause else ""
            return ToolResult(
                False,
                f"patch failed ({exc.stage}) at surface op {exc.surface_index} "
                f"[{where}]{detail}: {exc.message}",
            )
        parts = [f"patch applied; new snapshot: {result.snapshot_id}"]
        if result.errors:
            # best_effort：失败 op 已在 store 上跳过，这里逐条回报给模型
            parts.append(
                f"WARNING: {len(result.errors)} op(s) were NOT applied:"
            )
            for exc in result.errors:
                start, end = exc.position
                where = f"line {start}" if start == end else f"lines {start}-{end}"
                detail = f" ({exc.cause})" if exc.cause else ""
                parts.append(
                    f"  op {exc.surface_index} [{where}]{detail}: {exc.message}"
                )
        if not result.affected:
            parts.append("affected: none")
        for ab in result.affected:
            parts.append(f"[{ab.status}] {ab.agent_id}")
            if ab.annotated is not None:
                parts.append(ab.annotated.rstrip("\n"))
        # 有落地也有失败时 ok=True（状态已推进，失败只是警告）；
        # 全部失败（affected 空且有 errors）按未成功回报
        ok = not result.errors or bool(result.affected)
        return ToolResult(ok, "\n".join(parts))

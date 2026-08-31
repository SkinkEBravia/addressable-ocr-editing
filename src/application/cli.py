"""CLI：同一操作面的进程化封装（Docs/Design/07-agent-api.md「接口」节）。

各命令即链路片段的装配：

- ``ingest``   = sourceio.read + partition_chars + ir.birth + save
                 （并初始化会话目录，记录原文件绝对路径到 session.json）
- ``view``     = load(current) + present（默认组件）打印 payload
- ``patch``    = run_patch（load + parse + degrade + apply + save + 渲染）
- ``write``    = load + reconstruct + sourceio.write（缺省写回原文件路径）
- ``rollback`` = set_current

退出码：``0`` 成功；``1`` 解析失败（ParseError）；``2`` 降解失败；
``3`` apply 失败；``4`` I/O 失败（含 store / 会话目录错误）。

已知偏差：``--partition`` 用 argparse choices 限定为 ``chars``，传其他值时
argparse 以退出码 2 报用法错误（任务允许"退出码 4 或 argparse 错误"）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import ir
import sourceio
from partition import partition_chars
from reconstruction import reconstruct
from surface import ParseError, SurfaceError, run_patch
from view import blockkey_as_is, present, xml_ish

__all__ = ["main", "EX_OK", "EX_PARSE", "EX_DEGRADE", "EX_APPLY", "EX_IO"]

EX_OK = 0
EX_PARSE = 1
EX_DEGRADE = 2
EX_APPLY = 3
EX_IO = 4

_SESSION_META_NAME = "session.json"
_DEFAULT_PARTITION_SIZE = 1000


# ---------------------------------------------------------------------------
# 会话目录元数据
# ---------------------------------------------------------------------------

def _write_session_meta(store: ir.Store, source_path: Path) -> None:
    meta_path = store.root / _SESSION_META_NAME
    payload = {"source_path": str(source_path.resolve())}
    meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_session_meta(store: ir.Store) -> dict[str, Any] | None:
    meta_path = store.root / _SESSION_META_NAME
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def _fail(args: argparse.Namespace, code: int, payload: dict[str, Any], human: str) -> int:
    """错误输出双格式：-f json 时 JSON 到 stdout，否则人读文本到 stderr。"""
    if getattr(args, "format", "text") == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"error: {human}", file=sys.stderr)
    return code


def _surface_human(exc: SurfaceError) -> str:
    start, end = exc.position
    where = f"line {start}" if start == end else f"lines {start}-{end}"
    detail = f": {exc.cause}" if exc.cause else ""
    return (
        f"patch failed ({exc.stage}) at surface op {exc.surface_index} "
        f"({where}){detail}: {exc.message}"
    )


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------

def _cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        source = sourceio.read(path)
        result = partition_chars(source, args.size)
        snapshot = ir.birth(source, result)
        store = ir.Store(args.session)
        snapshot_id = ir.save(store, snapshot)
        _write_session_meta(store, path)
    except (OSError, sourceio.DecodeError, ir.PartitionError, ValueError) as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)},
                     f"ingest failed: {exc}")
    print(f"snapshot: {snapshot_id}")
    print(f"blocks: {len(snapshot.blocks)}")
    return EX_OK


def _cmd_view(args: argparse.Namespace) -> int:
    try:
        store = ir.Store(args.session)
        snapshot = ir.load(store, ir.current(store))
    except (ir.StoreError, OSError) as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)}, str(exc))
    agent_view = present(snapshot, blockkey_as_is, xml_ish)
    print(agent_view.payload, end="")
    return EX_OK


def _cmd_patch(args: argparse.Namespace) -> int:
    patch_text = sys.stdin.read()
    store = ir.Store(args.session)
    try:
        result = run_patch(store, patch_text, blockkey_as_is, xml_ish)
    except ParseError as exc:
        return _fail(args, EX_PARSE, exc.to_dict(),
                     f"parse failed: line {exc.line}: {exc.reason}")
    except SurfaceError as exc:
        code = EX_DEGRADE if exc.stage == "degrade" else EX_APPLY
        return _fail(args, code, exc.to_dict(), _surface_human(exc))
    except (ir.StoreError, OSError) as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)}, str(exc))

    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        print(f"snapshot: {result.snapshot_id}")
        if not result.affected:
            print("affected: none")
        for ab in result.affected:
            print(f"[{ab.status}] {ab.key} (agent id: {ab.agent_id})")
            if ab.annotated is not None:
                print(ab.annotated, end="")
    return EX_OK


def _cmd_write(args: argparse.Namespace) -> int:
    store = ir.Store(args.session)
    try:
        snapshot = ir.load(store, ir.current(store))
    except (ir.StoreError, OSError) as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)}, str(exc))
    source = reconstruct(snapshot)
    if args.output is not None:
        out_path = Path(args.output)
    else:
        meta = _read_session_meta(store)
        if meta is None or not isinstance(meta.get("source_path"), str):
            return _fail(
                args, EX_IO,
                {"error": "io", "message": "no source path recorded in session"},
                "no source path recorded in session directory; pass -o <path>",
            )
        out_path = Path(meta["source_path"])
    try:
        sourceio.write(out_path, source)
    except OSError as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)},
                     f"write failed: {exc}")
    print(f"written: {out_path}")
    return EX_OK


def _cmd_rollback(args: argparse.Namespace) -> int:
    try:
        ir.set_current(ir.Store(args.session), args.snapshot_id)
    except (ir.StoreError, OSError) as exc:
        return _fail(args, EX_IO, {"error": "io", "message": str(exc)}, str(exc))
    print(f"current: {args.snapshot_id}")
    return EX_OK


# ---------------------------------------------------------------------------
# 解析器与入口
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="application",
        description="块寻址文档 IR 的命令行操作面（patch 经 stdin 传入）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="读入文件，建立会话与初始快照")
    p_ingest.add_argument("file", help="源文件路径")
    p_ingest.add_argument("--session", required=True, help="会话目录")
    p_ingest.add_argument(
        "--partition", default="chars", choices=["chars"],
        help="分区策略（当前仅支持 chars）",
    )
    p_ingest.add_argument(
        "--size", type=int, default=_DEFAULT_PARTITION_SIZE,
        help=f"chars 分区的块大小（默认 {_DEFAULT_PARTITION_SIZE}）",
    )
    p_ingest.set_defaults(func=_cmd_ingest)

    p_view = sub.add_parser("view", help="打印当前快照的 AgentView payload")
    p_view.add_argument("--session", required=True, help="会话目录")
    p_view.set_defaults(func=_cmd_view)

    p_patch = sub.add_parser("patch", help="从 stdin 读 patch 文本并应用")
    p_patch.add_argument("--session", required=True, help="会话目录")
    p_patch.add_argument(
        "-f", "--format", default="text", choices=["text", "json"],
        help="输出格式（默认 text 人读；json 机读）",
    )
    p_patch.set_defaults(func=_cmd_patch)

    p_write = sub.add_parser("write", help="重建并写回文件")
    p_write.add_argument("--session", required=True, help="会话目录")
    p_write.add_argument(
        "-o", "--output", default=None,
        help="输出路径（缺省写回 ingest 时记录的原文件路径）",
    )
    p_write.set_defaults(func=_cmd_write)

    p_rollback = sub.add_parser("rollback", help="把当前指针移到已有快照")
    p_rollback.add_argument("snapshot_id", help="目标 SnapshotId")
    p_rollback.add_argument("--session", required=True, help="会话目录")
    p_rollback.set_defaults(func=_cmd_rollback)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)

"""patch 方言 ``fn`` 的解析器。

对应 Docs/Design/07-agent-api.md「方言 fn」节。一行一个函数调用::

    set_content(b3, "替换后的全文")
    set_attrs(b3, {"start": 120})
    append(b2, "新块内容")
    append(HEAD, "文首新块", {"kind": "intro"})
    remove(b4)
    move(b1, b5)
    merge(b1, b2)
    replace(b3, "teh", "the")

语法规则：

- 全部位置参数；id 为裸标识符（``HEAD`` 表示头部锚点，仅 anchor 位置合法）。
- 字符串与 attrs 对象使用 JSON 语法（转义、多行由 JSON 字符串承担）。
- 空行与 ``#`` 开头的行忽略。
- 解析不使用 eval：id 用标识符正则，其余用 ``json.JSONDecoder.raw_decode``
  受控解析。

任何语法错误抛 :class:`~surface.errors.ParseError`（含 1 起的行号与原因）。
"""

from __future__ import annotations

import json
import re

from surface.errors import ParseError
from surface.ops import (
    Append,
    LineSpan,
    Merge,
    Move,
    Remove,
    Replace,
    SetAttrs,
    SetContent,
    SurfaceOp,
)

__all__ = ["parse"]

_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\Z", re.DOTALL)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 各操作的参数个数区间 (min, max)
_ARITY: dict[str, tuple[int, int]] = {
    "set_content": (2, 2),
    "set_attrs": (2, 2),
    "append": (2, 3),
    "remove": (1, 1),
    "move": (2, 2),
    "merge": (2, 2),
    "replace": (3, 3),
}


class _Ident(str):
    """内部标记：裸标识符参数（区别于 JSON 字符串，两者解析后都是 str）。"""


def parse(patch_text: str) -> tuple[SurfaceOp, ...]:
    """patch 文本 -> SurfaceOp 序列（按文本顺序）。

    空行与 ``#`` 开头的行忽略；每条 op 记录其行号区间 ``position``。
    语法错误抛 ``ParseError``。
    """
    ops: list[SurfaceOp] = []
    for lineno, raw in enumerate(patch_text.split("\n"), start=1):
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        ops.append(_parse_line(line, lineno))
    return tuple(ops)


def _parse_line(line: str, lineno: int) -> SurfaceOp:
    m = _CALL_RE.match(line)
    if m is None:
        raise ParseError(lineno, f"expected `name(args)`, got: {line!r}")
    name, args_text = m.group(1), m.group(2)
    if name not in _ARITY:
        known = ", ".join(sorted(_ARITY))
        raise ParseError(lineno, f"unknown operation {name!r} (known: {known})")
    args = _parse_args(args_text, lineno)
    lo, hi = _ARITY[name]
    if not lo <= len(args) <= hi:
        expected = str(lo) if lo == hi else f"{lo}..{hi}"
        raise ParseError(
            lineno, f"{name} takes {expected} argument(s), got {len(args)}"
        )
    return _build_op(name, args, lineno)


def _parse_args(text: str, lineno: int) -> list[object]:
    """参数段 -> 参数值列表。

    裸标识符解析为 ``_Ident``；其余一律交给 ``json.JSONDecoder.raw_decode``
    （字符串 / 对象 / 数组 / 数字等，类型合法性由 ``_build_op`` 按操作检查）。
    """
    args: list[object] = []
    decoder = json.JSONDecoder()
    pos, n = 0, len(text)
    while True:
        pos = _skip_ws(text, pos)
        if pos >= n:
            break
        ch = text[pos]
        if ch.isalpha() or ch == "_":
            m = _IDENT_RE.match(text, pos)
            assert m is not None
            args.append(_Ident(m.group(0)))
            pos = m.end()
        else:
            try:
                value, pos = decoder.raw_decode(text, pos)
            except json.JSONDecodeError as exc:
                raise ParseError(lineno, f"invalid JSON: {exc.msg}") from exc
            args.append(value)
        pos = _skip_ws(text, pos)
        if pos >= n:
            break
        if text[pos] != ",":
            raise ParseError(
                lineno, f"expected ',' between arguments, got {text[pos]!r}"
            )
        pos = _skip_ws(text, pos + 1)
        if pos >= n:
            raise ParseError(lineno, "trailing comma")
    return args


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def _id(arg: object, name: str, lineno: int) -> str:
    if isinstance(arg, _Ident):
        return str(arg)
    if isinstance(arg, str):
        # JSON 字符串形式的 id 等价接受：id 与 content 同为字符串，
        # 类型直觉一致（模型天然会给 id 加引号）；放开只减失败不引矛盾。
        return arg
    raise ParseError(
        lineno, f"{name}: expected a block id (bare or quoted), got {arg!r}"
    )


def _text(arg: object, name: str, lineno: int) -> str:
    if type(arg) is str:  # 严格排除 _Ident
        return arg
    raise ParseError(lineno, f"{name}: text must be a JSON string, got {arg!r}")


def _obj(arg: object, name: str, lineno: int) -> dict:
    if isinstance(arg, dict):
        return arg
    raise ParseError(lineno, f"{name}: attrs must be a JSON object, got {arg!r}")


def _build_op(name: str, args: list[object], lineno: int) -> SurfaceOp:
    position: LineSpan = (lineno, lineno)
    match name:
        case "set_content":
            return SetContent(
                position=position,
                id=_id(args[0], name, lineno),
                text=_text(args[1], name, lineno),
            )
        case "set_attrs":
            return SetAttrs(
                position=position,
                id=_id(args[0], name, lineno),
                attrs=_obj(args[1], name, lineno),
            )
        case "append":
            return Append(
                position=position,
                anchor=_id(args[0], name, lineno),
                text=_text(args[1], name, lineno),
                attrs=_obj(args[2], name, lineno) if len(args) == 3 else None,
            )
        case "remove":
            return Remove(position=position, id=_id(args[0], name, lineno))
        case "move":
            return Move(
                position=position,
                id=_id(args[0], name, lineno),
                anchor=_id(args[1], name, lineno),
            )
        case "merge":
            return Merge(
                position=position,
                a=_id(args[0], name, lineno),
                b=_id(args[1], name, lineno),
            )
        case "replace":
            return Replace(
                position=position,
                id=_id(args[0], name, lineno),
                old=_text(args[1], name, lineno),
                new=_text(args[2], name, lineno),
            )
    raise AssertionError(f"unreachable: {name}")  # pragma: no cover

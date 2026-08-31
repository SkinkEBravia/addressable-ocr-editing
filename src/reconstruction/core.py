"""消费方：重建。DocumentSnapshot -> SourceText。

对应 Docs/Design/05-ir-io.md「统一输出接口 / 消费方：重建」节。

本模块是 IR 统一输出接口的消费方：纯函数、只读快照、无副作用。
作为消费方，允许 import ir 与 sourceio。

保真约定：``text = concat(b.content for b in blocks)``；
``encoding`` / ``bom`` 从 ``doc_attrs["source"]``（保留键，由 birth 写入）
取回，``bom`` 为十六进制字符串（空串 -> b""）；保留键缺失或字段非法时
回退 ``utf-8`` 无 BOM。配合 sourceio.write，未编辑的快照写回与原文件
逐字节相同（见 00-dataflow.md 的端到端等式）。
"""

from __future__ import annotations

from typing import Any

from ir import SOURCE_DOC_ATTR_KEY, DocumentSnapshot
from sourceio import SourceText

__all__ = ["reconstruct"]

_FALLBACK_ENCODING = "utf-8"


def _source_meta(snapshot: DocumentSnapshot) -> tuple[str, bytes]:
    """从 doc_attrs 的保留键取回 (encoding, bom)；缺失或非法时回退默认值。"""
    raw: Any = snapshot.doc_attrs.get(SOURCE_DOC_ATTR_KEY)
    if not isinstance(raw, dict):
        return _FALLBACK_ENCODING, b""

    encoding_raw: Any = raw.get("encoding")
    bom_raw: Any = raw.get("bom")

    encoding = encoding_raw if isinstance(encoding_raw, str) and encoding_raw else _FALLBACK_ENCODING
    bom = bytes.fromhex(bom_raw) if isinstance(bom_raw, str) else b""
    return encoding, bom


def reconstruct(snapshot: DocumentSnapshot) -> SourceText:
    """DocumentSnapshot -> SourceText（纯函数，只读）。

    - text = 按序拼接各块 content
    - encoding / bom 取自 ``doc_attrs["source"]``；缺失时回退 utf-8 无 BOM
    """
    text = "".join(b.content for b in snapshot.blocks)
    encoding, bom = _source_meta(snapshot)
    return SourceText(text=text, encoding=encoding, bom=bom)

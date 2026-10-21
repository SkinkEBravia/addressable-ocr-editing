"""消费方：重建。DocumentSnapshot -> SourceText。

对应 Docs/Design/05-ir-io.md「重建接口」节。

本模块是 IR 统一输出接口的消费方：纯函数、只读快照、无副作用。
作为消费方，允许 import ir 与 sourceio。

保真约定：``text = concat(b.content for b in blocks)``；
``encoding`` / ``bom`` 从 ``doc_attrs["source"]``（保留键，由 birth 写入）
取回，bom 为十六进制字符串。没有有效来源编码时回退 utf-8 无 BOM；
编码有效而 bom 缺失或非字符串时保留编码并使用空 BOM；非法十六进制
字符串抛 ValueError。完整保留来源信息的未编辑快照可逐字节还原，
见 00-overview.md 的输出链路。
"""

from __future__ import annotations

from ir import SOURCE_DOC_ATTR_KEY, DocumentSnapshot
from sourceio import SourceText

__all__ = ["reconstruct"]

_FALLBACK_ENCODING = "utf-8"


def reconstruct(snapshot: DocumentSnapshot) -> SourceText:
    """DocumentSnapshot -> SourceText（纯函数，只读）。

    - text = 按序拼接各块 content
    - 来源编码无效时回退 utf-8 无 BOM；仅 bom 缺失时保留编码、使用空 BOM。
    """
    text = "".join(b.content for b in snapshot.blocks)
    meta = snapshot.doc_attrs.get(SOURCE_DOC_ATTR_KEY)
    if isinstance(meta, dict) and isinstance(enc := meta.get("encoding"), str) and enc:
        raw_bom = meta.get("bom")
        bom = bytes.fromhex(raw_bom) if isinstance(raw_bom, str) else b""
        return SourceText(text=text, encoding=enc, bom=bom)
    return SourceText(text=text, encoding=_FALLBACK_ENCODING, bom=b"")

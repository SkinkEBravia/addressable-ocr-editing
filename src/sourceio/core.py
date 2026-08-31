"""文件级保真：bytes <-> SourceText。

本模块承担数据摄入的全部责任：BOM 检测、严格解码、无损回写。
不感知分区、块、文档层；不持有状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["SourceText", "DecodeError", "decode", "encode", "read", "write"]


class DecodeError(Exception):
    """解码失败。

    携带足够诊断信息：尝试的编码、原始字节长度、底层错误原因。
    """

    def __init__(self, message: str, *, encoding: str, raw_length: int) -> None:
        super().__init__(message)
        self.encoding = encoding
        self.raw_length = raw_length


@dataclass(frozen=True)
class SourceText:
    """一份文件的文本级表示，携带无损回写所需的全部元数据。"""

    text: str
    encoding: str
    bom: bytes


# BOM 检测链：先长后短、无歧义的三条规则。
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def decode(raw: bytes) -> SourceText:
    """bytes -> SourceText。

    1. 检测 BOM（utf-8-sig / utf-16-le / utf-16-be）；命中则按对应编码解码，
       BOM 字节记入 ``bom``，不进入 ``text``。
    2. 无 BOM 则按 UTF-8 严格解码，``bom = b""``。
    3. 解码失败抛 ``DecodeError``；不做编码猜测，不替换非法字节。

    换行符原样保留，不做任何转换。
    """
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            body = raw[len(bom):]
            try:
                text = body.decode(encoding, errors="strict")
            except UnicodeDecodeError as exc:
                raise DecodeError(
                    f"failed to decode {len(raw)} bytes as {encoding} "
                    f"(BOM {bom!r} detected): {exc}",
                    encoding=encoding,
                    raw_length=len(raw),
                ) from exc
            return SourceText(text=text, encoding=encoding, bom=bom)

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DecodeError(
            f"failed to decode {len(raw)} bytes as utf-8 (no BOM detected): {exc}",
            encoding="utf-8",
            raw_length=len(raw),
        ) from exc
    return SourceText(text=text, encoding="utf-8", bom=b"")


def encode(source: SourceText) -> bytes:
    """SourceText -> bytes：``bom + text.encode(encoding)``，无任何规整。"""
    return source.bom + source.text.encode(source.encoding)


def read(path: Path) -> SourceText:
    """二进制读文件 + decode。禁用隐式换行转换。"""
    return decode(Path(path).read_bytes())


def write(path: Path, source: SourceText) -> None:
    """encode + 二进制写文件。禁用隐式换行转换。"""
    Path(path).write_bytes(encode(source))

"""sourceio：文件级保真（bytes <-> SourceText）。"""

from sourceio.core import DecodeError, SourceText, decode, encode, read, write

__all__ = ["SourceText", "DecodeError", "decode", "encode", "read", "write"]

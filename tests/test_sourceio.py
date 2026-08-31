"""sourceio 验收与扩展测试。

验收（01-ingestion）：
- encode(decode(b)) == b
- write(path, read(path)) 后文件内容逐字节不变
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sourceio import DecodeError, SourceText, decode, encode, read, write

UTF8_BOM = b"\xef\xbb\xbf"
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"


class TestDecodeBom:
    def test_utf8_sig(self) -> None:
        s = decode(UTF8_BOM + "你好 world".encode("utf-8"))
        assert s.text == "你好 world"
        assert s.encoding == "utf-8"
        assert s.bom == UTF8_BOM
        assert UTF8_BOM.decode() not in s.text  # BOM 不进入 text

    def test_utf16_le(self) -> None:
        s = decode(UTF16_LE_BOM + "你好 world".encode("utf-16-le"))
        assert s.text == "你好 world"
        assert s.encoding == "utf-16-le"
        assert s.bom == UTF16_LE_BOM

    def test_utf16_be(self) -> None:
        s = decode(UTF16_BE_BOM + "你好 world".encode("utf-16-be"))
        assert s.text == "你好 world"
        assert s.encoding == "utf-16-be"
        assert s.bom == UTF16_BE_BOM

    def test_plain_utf8_no_bom(self) -> None:
        s = decode("héllo 世界".encode("utf-8"))
        assert s.text == "héllo 世界"
        assert s.encoding == "utf-8"
        assert s.bom == b""

    def test_bom_only(self) -> None:
        s = decode(UTF8_BOM)
        assert s.text == ""
        assert s.bom == UTF8_BOM

    def test_empty_bytes(self) -> None:
        s = decode(b"")
        assert s.text == ""
        assert s.encoding == "utf-8"
        assert s.bom == b""

    def test_newlines_preserved(self) -> None:
        text = "a\r\nb\rc\nd"
        s = decode(text.encode("utf-8"))
        assert s.text == text  # \r\n / \r / \n 原样保留

    def test_invalid_utf8_raises(self) -> None:
        with pytest.raises(DecodeError) as exc_info:
            decode(b"\x80\x81\xfe")  # 非法 UTF-8，且无 BOM
        assert exc_info.value.encoding == "utf-8"
        assert exc_info.value.raw_length == 3

    def test_invalid_utf16_body_raises(self) -> None:
        with pytest.raises(DecodeError):
            decode(UTF16_LE_BOM + b"\x00")  # 奇数字节，非法 UTF-16

    def test_no_encoding_guess_for_gbk(self) -> None:
        with pytest.raises(DecodeError):
            decode("你好".encode("gbk"))  # GBK 字节不是合法 UTF-8，必须报错而非猜测


class TestRoundTrip:
    """encode(decode(b)) == b，逐字节相等。"""

    @pytest.mark.parametrize(
        "raw",
        [
            "plain ascii".encode("utf-8"),
            UTF8_BOM + "你好 world".encode("utf-8"),
            UTF16_LE_BOM + "你好 world".encode("utf-16-le"),
            UTF16_BE_BOM + "你好 world".encode("utf-16-be"),
            "a\r\nb\rc\nd\r\n".encode("utf-8"),  # 混合换行
            b"",  # 空字节串
            "emoji 🚀🎉 and accents àéîõü".encode("utf-8"),
            UTF8_BOM,  # 仅 BOM
            "no trailing newline".encode("utf-8"),
            "trailing newline\n".encode("utf-8"),
        ],
        ids=[
            "utf8-no-bom",
            "utf8-sig",
            "utf16-le",
            "utf16-be",
            "mixed-newlines",
            "empty",
            "non-ascii",
            "bom-only",
            "no-trailing-newline",
            "trailing-newline",
        ],
    )
    def test_encode_decode_identity(self, raw: bytes) -> None:
        assert encode(decode(raw)) == raw

    def test_write_read_byte_identical(self, tmp_path: Path) -> None:
        raw = UTF16_LE_BOM + "a\r\nb\rc\n你好".encode("utf-16-le")
        path = tmp_path / "doc.txt"
        path.write_bytes(raw)
        write(path, read(path))
        assert path.read_bytes() == raw

    def test_write_no_newline_translation(self, tmp_path: Path) -> None:
        # Windows 上文本模式会把 \n 翻译成 \r\n；二进制写必须原样落盘
        source = SourceText(text="x\ny\r\nz\r", encoding="utf-8", bom=b"")
        path = tmp_path / "nl.txt"
        write(path, source)
        assert path.read_bytes() == "x\ny\r\nz\r".encode("utf-8")

    def test_encode_is_pure(self) -> None:
        s = decode(UTF8_BOM + "abc".encode("utf-8"))
        assert encode(s) == encode(s)

    @given(st.text())
    def test_property_utf8_roundtrip(self, text: str) -> None:
        raw = text.encode("utf-8")
        assert encode(decode(raw)) == raw

    @given(st.text())
    def test_property_utf16_roundtrip(self, text: str) -> None:
        for enc, bom in (("utf-16-le", UTF16_LE_BOM), ("utf-16-be", UTF16_BE_BOM)):
            raw = bom + text.encode(enc)
            assert encode(decode(raw)) == raw

    @given(st.binary())
    def test_property_decode_never_guesses(self, raw: bytes) -> None:
        # 任意字节：要么成功且往返无损，要么抛 DecodeError；绝不静默替换
        try:
            result = decode(raw)
        except DecodeError:
            return
        assert encode(result) == raw

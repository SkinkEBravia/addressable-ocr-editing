"""reconstruction 消费方的测试。

覆盖：
- reconstruct -> encode 与原文逐字节相同（utf-8 无 BOM / utf-8-sig /
  utf-16-le 带 BOM / CRLF 混合）
- 来源编码无效时回退 utf-8 无 BOM；仅 bom 缺失时保留原编码
- 端到端等式（00-dataflow.md 的总闸）：tmp 文件 -> sourceio.read ->
  partition_chars -> birth -> reconstruct -> sourceio.write ->
  逐字节等于原文件（含非 ASCII、CRLF、空文件）
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ir import DocumentSnapshot, birth
from partition import partition_chars
from reconstruction import reconstruct
from sourceio import SourceText, decode, encode, read, write

CASES: list[tuple[str, bytes]] = [
    ("utf-8 无 BOM", "hello, world\n第二行\n".encode("utf-8")),
    ("utf-8-sig", b"\xef\xbb\xbf" + "带 BOM 的 utf-8\ntext\n".encode("utf-8")),
    ("utf-16-le 带 BOM", b"\xff\xfe" + "你好，世界\r\nsecond line\n".encode("utf-16-le")),
    ("CRLF 混合", "a\r\nb\nc\r\n中文 tail".encode("utf-8")),
]


def _roundtrip_through_ir(raw: bytes, size: int = 7) -> bytes:
    """decode -> partition_chars -> birth -> reconstruct -> encode。"""
    source = decode(raw)
    snapshot = birth(source, partition_chars(source, size))
    return encode(reconstruct(snapshot))


class TestReconstructByteExact:
    @pytest.mark.parametrize("label,raw", CASES, ids=[c[0] for c in CASES])
    def test_encode_matches_original_bytes(self, label: str, raw: bytes) -> None:
        assert _roundtrip_through_ir(raw) == raw

    def test_metadata_roundtrip(self) -> None:
        raw = b"\xef\xbb\xbf" + "meta 测试\n".encode("utf-8")
        source = decode(raw)
        snapshot = birth(source, partition_chars(source, 3))
        out = reconstruct(snapshot)
        assert out.encoding == "utf-8"
        assert out.bom == b"\xef\xbb\xbf"
        assert out.text == source.text

    def test_empty_text(self) -> None:
        raw = b""
        source = decode(raw)
        snapshot = birth(source, partition_chars(source, 5))
        out = reconstruct(snapshot)
        assert out == SourceText(text="", encoding="utf-8", bom=b"")
        assert encode(out) == raw


class TestSourceMetaFallback:
    def _snapshot_without_source_key(self) -> DocumentSnapshot:
        return DocumentSnapshot(
            id="s-test",
            blocks=(),
            doc_attrs={"partition": "chars", "size": 5},
            key_cursor=1,
        )

    def test_missing_source_key_falls_back_to_utf8_no_bom(self) -> None:
        out = reconstruct(self._snapshot_without_source_key())
        assert out.encoding == "utf-8"
        assert out.bom == b""
        assert out.text == ""

    def test_malformed_source_key_falls_back(self) -> None:
        snapshot = DocumentSnapshot(
            id="s-test",
            blocks=(),
            doc_attrs={"source": "not-a-dict"},
            key_cursor=1,
        )
        out = reconstruct(snapshot)
        assert out.encoding == "utf-8"
        assert out.bom == b""

    def test_partial_source_fields_fall_back_individually(self) -> None:
        snapshot = DocumentSnapshot(
            id="s-test",
            blocks=(),
            doc_attrs={"source": {"encoding": "utf-16-le"}},  # 缺 bom
            key_cursor=1,
        )
        out = reconstruct(snapshot)
        assert out.encoding == "utf-16-le"
        assert out.bom == b""


class TestEndToEndEquation:
    """00-dataflow.md 的总闸：ingest 后不编辑直接写出，与原文件逐字节相同。"""

    E2E_CASES: list[tuple[str, bytes]] = [
        ("非 ASCII + utf-8-sig", b"\xef\xbb\xbf" + "标题\r\n\r\n正文：αβγ、中文、emoji 🌍\n".encode("utf-8")),
        ("utf-16-le 带 BOM", b"\xff\xfe" + "行一\r\n行二 中文\n".encode("utf-16-le")),
        ("CRLF 混合无 BOM", "first\r\nsecond\nthird\r\n".encode("utf-8")),
        ("空文件", b""),
    ]

    @pytest.mark.parametrize("label,raw", E2E_CASES, ids=[c[0] for c in E2E_CASES])
    def test_file_roundtrip_byte_identical(self, tmp_path: Path, label: str, raw: bytes) -> None:
        src = tmp_path / "in.txt"
        src.write_bytes(raw)

        source = read(src)
        snapshot = birth(source, partition_chars(source, 13))
        out = tmp_path / "out.txt"
        write(out, reconstruct(snapshot))

        assert out.read_bytes() == raw

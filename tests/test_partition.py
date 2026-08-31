"""partition 验收与扩展测试。

验收（02-partition）：
- concat(blocks[*].content) == source.text（严格分区）
- json 序列化 -> 反序列化 == 原 PartitionResult
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from partition import (
    BlockDraft,
    PartitionResult,
    from_json,
    partition_chars,
    to_json,
)


@dataclass(frozen=True)
class FakeSource:
    """结构性输入替身：partition 不得 import sourceio，只需 .text。"""

    text: str


def concat(result: PartitionResult) -> str:
    return "".join(b.content for b in result.blocks)


class TestPartitionChars:
    def test_even_split(self) -> None:
        r = partition_chars(FakeSource("abcdef"), 2)
        assert [b.content for b in r.blocks] == ["ab", "cd", "ef"]

    def test_last_block_may_be_short(self) -> None:
        r = partition_chars(FakeSource("abcde"), 2)
        assert [b.content for b in r.blocks] == ["ab", "cd", "e"]

    def test_empty_text_empty_blocks(self) -> None:
        r = partition_chars(FakeSource(""), 4)
        assert r.blocks == ()
        assert concat(r) == ""

    def test_size_larger_than_text(self) -> None:
        r = partition_chars(FakeSource("abc"), 100)
        assert [b.content for b in r.blocks] == ["abc"]

    def test_size_one(self) -> None:
        r = partition_chars(FakeSource("abc"), 1)
        assert [b.content for b in r.blocks] == ["a", "b", "c"]

    def test_start_offsets(self) -> None:
        text = "abcdefg"
        r = partition_chars(FakeSource(text), 3)
        starts = [b.attrs["start"] for b in r.blocks]
        assert starts == [0, 3, 6]
        for block in r.blocks:
            start = block.attrs["start"]
            assert text[start : start + len(block.content)] == block.content

    def test_doc_attrs(self) -> None:
        r = partition_chars(FakeSource("hello"), 2)
        assert r.doc_attrs == {"partition": "chars", "size": 2}

    def test_unicode_counts_characters_not_bytes(self) -> None:
        r = partition_chars(FakeSource("你好世界🚀"), 2)
        assert [b.content for b in r.blocks] == ["你好", "世界", "🚀"]
        assert [b.attrs["start"] for b in r.blocks] == [0, 2, 4]

    def test_invalid_size(self) -> None:
        for bad in (0, -1):
            with pytest.raises(ValueError):
                partition_chars(FakeSource("abc"), bad)

    def test_accepts_any_object_with_text(self) -> None:
        class Bare:
            text = "abcd"

        r = partition_chars(Bare(), 3)
        assert [b.content for b in r.blocks] == ["abc", "d"]

    def test_does_not_rewrite_text(self) -> None:
        text = "a\r\nb\rc\nd  spaced "
        r = partition_chars(FakeSource(text), 2)
        assert concat(r) == text

    def test_blockdraft_is_frozen(self) -> None:
        b = BlockDraft(content="x", attrs={})
        with pytest.raises(FrozenInstanceError):
            b.content = "y"  # type: ignore[misc]

    def test_result_is_frozen(self) -> None:
        r = partition_chars(FakeSource("ab"), 1)
        with pytest.raises(FrozenInstanceError):
            r.blocks = ()  # type: ignore[misc]

    @given(st.text(), st.integers(min_value=1, max_value=64))
    def test_property_strict_partition_identity(self, text: str, size: int) -> None:
        r = partition_chars(FakeSource(text), size)
        assert concat(r) == text
        if text:
            assert [b.attrs["start"] for b in r.blocks] == list(range(0, len(text), size))
            assert all(len(b.content) <= size for b in r.blocks)
            assert all(len(b.content) == size for b in r.blocks[:-1])
        else:
            assert r.blocks == ()


class TestJsonRoundTrip:
    def test_json_roundtrip(self) -> None:
        r = partition_chars(FakeSource("hello world"), 4)
        assert from_json(to_json(r)) == r

    def test_json_roundtrip_empty(self) -> None:
        r = partition_chars(FakeSource(""), 4)
        assert from_json(to_json(r)) == r

    def test_json_is_plain_json(self) -> None:
        r = partition_chars(FakeSource("abcd"), 2)
        payload = json.loads(to_json(r))
        assert payload == {
            "blocks": [
                {"content": "ab", "attrs": {"start": 0}},
                {"content": "cd", "attrs": {"start": 2}},
            ],
            "doc_attrs": {"partition": "chars", "size": 2},
        }

    def test_json_roundtrip_preserves_attrs_types(self) -> None:
        r = PartitionResult(
            blocks=(
                BlockDraft(
                    content="x",
                    attrs={"start": 0, "tags": ["a", "b"], "meta": {"n": 1.5, "ok": True, "none": None}},
                ),
            ),
            doc_attrs={"partition": "chars", "size": 3},
        )
        assert from_json(to_json(r)) == r

    @given(st.text(), st.integers(min_value=1, max_value=32))
    def test_property_json_roundtrip(self, text: str, size: int) -> None:
        r = partition_chars(FakeSource(text), size)
        assert from_json(to_json(r)) == r

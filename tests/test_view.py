"""view 消费方的测试。

对应 06-view.md 的验收：
- reference_map 为双射且覆盖全部 blocks
- 同一 (snapshot, strategy, annotator) 重复 present，payload 与
  reference_map 相同（view_id 可不同）

另覆盖：重复 id 抛 ViewError、xml_ish 逐字符断言、render_blocks 子集渲染
与全量一致、空快照 payload 为空串。
"""

from __future__ import annotations

import pytest
from ir import Block, DocumentSnapshot, birth
from partition import partition_chars
from sourceio import decode
from view import (
    AgentView,
    ReferenceMap,
    ViewError,
    blockkey_as_is,
    file_header,
    prefixed_blockkey,
    present,
    render_blocks,
    xml_ish,
)


def _snapshot(text: str, size: int = 4) -> DocumentSnapshot:
    source = decode(text.encode("utf-8"))
    return birth(source, partition_chars(source, size))


class TestXmlIsh:
    def test_exact_format(self) -> None:
        assert xml_ish("b3", "块内容原文") == '<x id="b3"\\>\n块内容原文\n</x>\n'

    def test_content_not_escaped(self) -> None:
        # 内容原样，不转义；标注中的 \> 使整体非良构 XML
        out = xml_ish("b1", '<a href="x">自带 XML</a>')
        assert out == '<x id="b1"\\>\n<a href="x">自带 XML</a>\n</x>\n'

    def test_open_tag_contains_literal_backslash_gt(self) -> None:
        assert xml_ish("k", "").startswith('<x id="k"' + "\\" + ">")


class TestBlockkeyAsIs:
    def test_returns_block_key(self) -> None:
        block = Block(key="b7", content="x", attrs={"start": 0})
        assert blockkey_as_is(block, 0) == "b7"
        assert blockkey_as_is(block, 99) == "b7"  # 与下标无关


class TestPresent:
    def test_reference_map_bijective_and_covers_all_blocks(self) -> None:
        snapshot = _snapshot("一二三四五六七八九十", size=3)
        view = present(snapshot, blockkey_as_is, xml_ish)

        assert isinstance(view, AgentView)
        ref = view.reference_map
        # 覆盖全部 blocks
        assert len(ref) == len(snapshot.blocks)
        assert set(ref.as_dict().values()) == {b.key for b in snapshot.blocks}
        # 双射：正向唯一 + 反向可回查
        assert len(set(ref.as_dict())) == len(snapshot.blocks)
        for block in snapshot.blocks:
            agent_id = ref.agent_id_of(block.key)
            assert ref.key_of(agent_id) == block.key

    def test_repeated_present_is_deterministic(self) -> None:
        snapshot = _snapshot("abcdefgh", size=2)
        v1 = present(snapshot, blockkey_as_is, xml_ish)
        v2 = present(snapshot, blockkey_as_is, xml_ish)

        assert v1.payload == v2.payload
        assert v1.reference_map.as_dict() == v2.reference_map.as_dict()
        assert v1.snapshot_id == v2.snapshot_id == snapshot.id
        assert v1.view_id != v2.view_id  # 身份可不同，内容由 (snapshot, strategy, annotator) 确定

    def test_render_spec_records_component_names(self) -> None:
        snapshot = _snapshot("ab", size=1)
        view = present(snapshot, blockkey_as_is, xml_ish)
        assert view.render_spec == {
            "kind": "agent",
            "strategy": "blockkey_as_is",
            "annotator": "xml_ish",
        }

    def test_duplicate_agent_id_raises_view_error(self) -> None:
        snapshot = _snapshot("abcd", size=1)  # 4 块

        def constant_strategy(block: Block, index: int) -> str:
            return "same"

        with pytest.raises(ViewError):
            present(snapshot, constant_strategy, xml_ish)

    def test_payload_concatenates_annotations_in_order(self) -> None:
        snapshot = _snapshot("abcd", size=2)  # b1="ab", b2="cd"
        view = present(snapshot, blockkey_as_is, xml_ish)
        expected = xml_ish("b1", "ab") + xml_ish("b2", "cd")
        assert view.payload == expected

    def test_empty_snapshot_payload_is_empty_string(self) -> None:
        snapshot = _snapshot("", size=5)
        assert snapshot.blocks == ()
        view = present(snapshot, blockkey_as_is, xml_ish)
        assert view.payload == ""
        assert len(view.reference_map) == 0


class TestRenderBlocks:
    def test_subset_rendering_matches_full_view_fragment(self) -> None:
        snapshot = _snapshot("0123456789abcdef", size=3)
        full_payload, full_map = render_blocks(snapshot.blocks, blockkey_as_is, xml_ish)

        subset = snapshot.blocks[1:3]
        sub_payload, sub_map = render_blocks(subset, blockkey_as_is, xml_ish)

        # 子集渲染 = 全量 payload 中对应片段逐字符一致
        expected_fragment = "".join(xml_ish(b.key, b.content) for b in subset)
        assert sub_payload == expected_fragment
        assert expected_fragment in full_payload
        # 子集 map 与全量 map 在这些块上一致
        for b in subset:
            assert sub_map[b.key] == full_map[b.key]

    def test_empty_blocks(self) -> None:
        payload, ref = render_blocks((), blockkey_as_is, xml_ish)
        assert payload == ""
        assert len(ref) == 0

    def test_duplicate_id_raises_view_error(self) -> None:
        snapshot = _snapshot("ab", size=1)
        with pytest.raises(ViewError):
            render_blocks(snapshot.blocks, lambda block, index: "dup", xml_ish)


class TestReferenceMap:
    def test_non_bijective_dict_rejected(self) -> None:
        with pytest.raises(ViewError):
            ReferenceMap({"a1": "b1", "a2": "b1"})

    def test_as_dict_returns_copy(self) -> None:
        ref = ReferenceMap({"a1": "b1"})
        copy = ref.as_dict()
        copy["a2"] = "b2"
        assert len(ref) == 1

    def test_lookup_helpers(self) -> None:
        ref = ReferenceMap({"a1": "b1"})
        assert ref["a1"] == "b1"
        assert ref.agent_id_of("b1") == "a1"
        assert "a1" in ref
        with pytest.raises(KeyError):
            ref["nope"]
        with pytest.raises(KeyError):
            ref.agent_id_of("nope")


class TestPrefixedAndFileView:
    def test_prefixed_blockkey_strategy(self) -> None:
        block = Block(key="b1", content="hello", attrs={"start": 0})
        strategy = prefixed_blockkey("c0")
        assert strategy(block, 0) == "c0:b1"

    def test_file_header_annotator(self) -> None:
        annotator = file_header("chunk_0.txt", xml_ish)
        out = annotator("c0:b1", "sample content")
        assert out == '<x id="c0:b1"\\>\nsample content\n</x>\n'

    def test_present_with_file_and_prefix(self) -> None:
        snapshot = _snapshot("一二三四五六", size=3)
        # present_file: 开头带文件提示，且各块带前缀
        from view import present_file
        view = present_file(snapshot, "chunk_0", "c0")
        assert view.payload.startswith("--- [File: chunk_0] ---\n")
        assert '<x id="c0:b1"\\>' in view.payload
        assert view.reference_map["c0:b1"] == "b1"
        assert view.reference_map.agent_id_of("b1") == "c0:b1"

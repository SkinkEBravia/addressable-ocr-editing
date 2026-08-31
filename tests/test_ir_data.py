"""03-ir-data.md 验收：JSON 往返相等、key 互不相同且无 HEAD、分配器与 SnapshotId。"""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from ir import (
    HEAD,
    SPEC,
    Block,
    DocumentSnapshot,
    alloc,
    canonical_json,
    snapshot_dumps,
    snapshot_from_dict,
    snapshot_id,
    snapshot_loads,
    snapshot_to_dict,
)


def make_snapshot(n: int = 3) -> DocumentSnapshot:
    blocks = tuple(
        Block(key=f"b{i}", content=f"段{i}。", attrs={"start": i * 10})
        for i in range(1, n + 1)
    )
    s = DocumentSnapshot(
        id="", blocks=blocks, doc_attrs={"partition": "chars", "size": 10},
        key_cursor=n + 1,
    )
    return replace(s, id=snapshot_id(s))


class TestJsonRoundTrip:
    """验收：json.loads(json.dumps(snapshot)) == snapshot。"""

    def test_roundtrip_via_helpers(self):
        s = make_snapshot()
        assert snapshot_loads(snapshot_dumps(s)) == s

    def test_roundtrip_bare_json(self):
        s = make_snapshot()
        data = json.loads(json.dumps(snapshot_to_dict(s), ensure_ascii=False))
        assert snapshot_from_dict(data) == s

    def test_roundtrip_empty_blocks_and_nested_attrs(self):
        s = DocumentSnapshot(
            id="",
            blocks=(),
            doc_attrs={"nested": {"a": [1, 1.5, None, True, "x"]}},
            key_cursor=1,
        )
        s = replace(s, id=snapshot_id(s))
        assert snapshot_loads(snapshot_dumps(s)) == s

    def test_logical_format_shape(self):
        s = make_snapshot(2)
        data = snapshot_to_dict(s)
        assert data["spec"] == SPEC == 1
        assert data["id"] == s.id
        assert data["key_cursor"] == 3
        assert [b["key"] for b in data["blocks"]] == ["b1", "b2"]
        assert set(data["blocks"][0]) == {"key", "content", "attrs"}

    def test_from_dict_rejects_bad_spec(self):
        data = snapshot_to_dict(make_snapshot(1))
        data["spec"] = 999
        with pytest.raises(ValueError):
            snapshot_from_dict(data)

    def test_from_dict_rejects_duplicate_keys(self):
        data = snapshot_to_dict(make_snapshot(2))
        data["blocks"][1]["key"] = "b1"
        with pytest.raises(ValueError):
            snapshot_from_dict(data)

    def test_from_dict_rejects_head_key(self):
        data = snapshot_to_dict(make_snapshot(1))
        data["blocks"][0]["key"] = HEAD
        with pytest.raises(ValueError):
            snapshot_from_dict(data)


class TestKeys:
    """验收：blocks 内 key 互不相同，且无 key == HEAD。"""

    def test_keys_unique_and_no_head(self):
        s = make_snapshot(5)
        keys = [b.key for b in s.blocks]
        assert len(set(keys)) == len(keys)
        assert HEAD not in keys

    def test_head_constant(self):
        assert HEAD == "head"


class TestAlloc:
    def test_alloc_key_and_cursor(self):
        s = make_snapshot(3)
        key, new_cursor = alloc(s)
        assert key == "b4"
        assert new_cursor == 5

    def test_alloc_does_not_mutate(self):
        s = make_snapshot(3)
        alloc(s)
        assert s.key_cursor == 4


class TestSnapshotId:
    def test_format(self):
        sid = snapshot_id(make_snapshot())
        assert re.fullmatch(r"s-[0-9a-f]{16}", sid)

    def test_content_addressed(self):
        """相同内容（id 字段除外）得到相同 id：分叉安全。"""
        a = make_snapshot()
        b = replace(make_snapshot(), id="s-ffffffffffffffff")
        assert snapshot_id(a) == snapshot_id(b)

    def test_content_changes_id(self):
        a = make_snapshot()
        b = replace(a, key_cursor=a.key_cursor + 1)
        assert snapshot_id(a) != snapshot_id(b)

    def test_canonical_json_definition(self):
        obj = {"b": 1, "a": ["汉", None]}
        assert canonical_json(obj) == '{"a":["汉",null],"b":1}'

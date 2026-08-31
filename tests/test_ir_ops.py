"""04-ir-ops.md 验收：apply 的纯函数性、原子性、Append/Remove/Set* 语义。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ir import (
    ANCHOR_IS_REMOVED,
    BAD_ANCHOR,
    HEAD,
    KEY_NOT_FOUND,
    Append,
    Block,
    DocumentSnapshot,
    OpError,
    Remove,
    SetAttrs,
    SetContent,
    apply,
    snapshot_id,
)


def make_snapshot(n: int = 3) -> DocumentSnapshot:
    blocks = tuple(
        Block(key=f"b{i}", content=f"段{i}。", attrs={"start": i})
        for i in range(1, n + 1)
    )
    s = DocumentSnapshot(
        id="", blocks=blocks, doc_attrs={"partition": "chars"}, key_cursor=n + 1
    )
    return replace(s, id=snapshot_id(s))


def keys(s: DocumentSnapshot) -> list[str]:
    return [b.key for b in s.blocks]


class TestEmptyBatch:
    """验收：apply(s, ()) == s（同一对象，不产出新 SnapshotId）。"""

    def test_empty_ops_returns_same_object(self):
        s = make_snapshot()
        assert apply(s, ()) is s


class TestPurityAndAtomicity:
    def test_original_snapshot_unchanged(self):
        s = make_snapshot()
        before = s  # frozen：任何改动都会破坏相等性
        apply(s, (SetContent("b1", "改写"), Remove("b3"), Append("新", {}, at="b1")))
        assert s == before
        assert keys(s) == ["b1", "b2", "b3"]

    def test_atomic_failure(self):
        """验收：批次中任一失败 ⇒ 无新快照，s 不变，OpError.index 指向失败条。"""
        s = make_snapshot()
        ops = (SetContent("b1", "改写"), Remove("不存在"), Append("x", {}, at=HEAD))
        with pytest.raises(OpError) as exc_info:
            apply(s, ops)
        err = exc_info.value
        assert err.index == 1
        assert err.op is ops[1]
        assert err.reason == KEY_NOT_FOUND
        assert err.key == "不存在"
        assert s == make_snapshot()  # 原快照不变

    def test_failure_at_first_op_reports_index_zero(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (Remove("不存在"),))
        assert exc_info.value.index == 0

    def test_pure_function_deterministic(self):
        """apply 是纯函数：同一输入试跑两次得到完全相等的新快照（同 id）。"""
        s = make_snapshot()
        ops = (Append("新", {"k": 1}, at="b2"),)
        assert apply(s, ops) == apply(s, ops)

    def test_unknown_op_type(self):
        s = make_snapshot()
        with pytest.raises(TypeError):
            apply(s, (object(),))  # type: ignore[arg-type]


class TestAppend:
    def test_append_to_head_inserts_front(self):
        s = make_snapshot()
        s2 = apply(s, (Append("首", {"pos": "front"}, at=HEAD),))
        assert keys(s2) == ["b4", "b1", "b2", "b3"]
        assert s2.blocks[0].content == "首"
        assert s2.blocks[0].attrs == {"pos": "front"}

    def test_append_after_middle_key(self):
        s = make_snapshot()
        s2 = apply(s, (Append("中", {}, at="b1"),))
        assert keys(s2) == ["b1", "b4", "b2", "b3"]

    def test_append_after_last_key_appends_tail(self):
        s = make_snapshot()
        s2 = apply(s, (Append("尾", {}, at="b3"),))
        assert keys(s2) == ["b1", "b2", "b3", "b4"]

    def test_append_advances_cursor_and_id(self):
        s = make_snapshot()
        s2 = apply(s, (Append("x", {}, at=HEAD),))
        assert s2.key_cursor == s.key_cursor + 1
        assert s2.id != s.id
        assert s2.id.startswith("s-")

    def test_append_bad_anchor(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (Append("x", {}, at="b99"),))
        assert exc_info.value.reason == BAD_ANCHOR
        assert exc_info.value.key == "b99"

    def test_append_anchor_is_removed(self):
        s = make_snapshot()
        s2 = apply(s, (Remove("b2"),))
        with pytest.raises(OpError) as exc_info:
            apply(s2, (Append("x", {}, at="b2"),))
        assert exc_info.value.reason == ANCHOR_IS_REMOVED
        assert exc_info.value.key == "b2"

    def test_append_copies_draft_attrs(self):
        """块坯的 attrs 被拷贝：事后修改入参不影响快照。"""
        s = make_snapshot()
        attrs = {"k": 1}
        s2 = apply(s, (Append("x", attrs, at=HEAD),))
        attrs["k"] = 999
        assert s2.blocks[0].attrs == {"k": 1}


class TestRemove:
    def test_remove(self):
        s = make_snapshot()
        s2 = apply(s, (Remove("b2"),))
        assert keys(s2) == ["b1", "b3"]

    def test_removed_key_not_reused(self):
        """key 作废不复用：cursor 不回退，新块取新号。"""
        s = make_snapshot()
        s2 = apply(s, (Remove("b2"),))
        assert s2.key_cursor == s.key_cursor  # 4，不回退
        s3 = apply(s2, (Append("新", {}, at=HEAD),))
        assert "b2" not in keys(s3)
        assert keys(s3)[0] == "b4"

    def test_remove_missing_key(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (Remove("b9"),))
        assert exc_info.value.reason == KEY_NOT_FOUND

    def test_remove_head_rejected(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (Remove(HEAD),))
        assert exc_info.value.reason == KEY_NOT_FOUND
        assert exc_info.value.key == HEAD

    def test_remove_same_key_twice_in_batch_fails(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (Remove("b1"), Remove("b1")))
        assert exc_info.value.index == 1


class TestSetContentAndAttrs:
    def test_set_content_replaces(self):
        s = make_snapshot()
        s2 = apply(s, (SetContent("b2", "新内容"),))
        assert s2.blocks[1].content == "新内容"
        assert s2.blocks[1].attrs == {"start": 2}  # attrs 不动

    def test_set_attrs_replaces_wholesale(self):
        """整体替换：旧键不保留（合并归调用方负责）。"""
        s = make_snapshot()
        s2 = apply(s, (SetAttrs("b2", {"brand": "new"}),))
        assert s2.blocks[1].attrs == {"brand": "new"}

    def test_set_content_missing_key(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (SetContent("b9", "x"),))
        assert exc_info.value.reason == KEY_NOT_FOUND

    def test_set_attrs_missing_key(self):
        s = make_snapshot()
        with pytest.raises(OpError) as exc_info:
            apply(s, (SetAttrs("b9", {}),))
        assert exc_info.value.reason == KEY_NOT_FOUND


class TestBatchSemantics:
    def test_batch_applies_in_order(self):
        """批次内后面的 op 看到前面 op 的结果（含新装订的 key）。"""
        s = make_snapshot()
        s2 = apply(
            s,
            (
                Append("甲", {}, at="b1"),      # 装订为 b4
                Append("乙", {}, at="b4"),      # 插在 b4 之后，装订为 b5
                SetContent("b5", "乙改"),
            ),
        )
        assert keys(s2) == ["b1", "b4", "b5", "b2", "b3"]
        assert s2.blocks[2].content == "乙改"
        assert s2.key_cursor == 6

    def test_doc_attrs_unchanged(self):
        s = make_snapshot()
        s2 = apply(s, (Remove("b1"),))
        assert s2.doc_attrs == s.doc_attrs

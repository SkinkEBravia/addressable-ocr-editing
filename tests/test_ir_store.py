"""05-ir-io.md 验收：birth（出生）与 Store（持久化 / 指针）。

birth 的用例以结构性假对象（SimpleNamespace）喂入，验证 ir 不 import
sourceio / partition 也能工作（Protocol 鸭子类型）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ir import (
    Append,
    Block,
    DocumentSnapshot,
    PartitionError,
    SetContent,
    Store,
    StoreError,
    apply,
    birth,
    current,
    load,
    save,
    set_current,
    snapshot_id,
)

# ---------------------------------------------------------------------------
# 出生（birth）
# ---------------------------------------------------------------------------


def fake_source(text: str, encoding: str = "utf-8", bom: bytes = b""):
    return SimpleNamespace(text=text, encoding=encoding, bom=bom)


def fake_result(texts: list[str], doc_attrs=None):
    blocks = tuple(
        SimpleNamespace(content=t, attrs={"start": i}) for i, t in enumerate(texts)
    )
    return SimpleNamespace(blocks=blocks, doc_attrs=doc_attrs or {"partition": "chars"})


class TestBirth:
    def test_birth_basic(self):
        source = fake_source("第一段。第二段。第三段。")
        result = fake_result(["第一段。", "第二段。", "第三段。"])
        s = birth(source, result)
        assert [b.key for b in s.blocks] == ["b1", "b2", "b3"]
        assert [b.content for b in s.blocks] == ["第一段。", "第二段。", "第三段。"]
        assert s.key_cursor == 4  # 从 1 起装订，游标指向下一个号
        assert s.id.startswith("s-")

    def test_birth_empty_partition(self):
        s = birth(fake_source(""), fake_result([]))
        assert s.blocks == ()
        assert s.key_cursor == 1

    def test_birth_strict_partition_check(self):
        """concat != source.text ⇒ PartitionError（验收点在边界）。"""
        source = fake_source("原文。")
        result = fake_result(["原文。", "多出来的一段。"])
        with pytest.raises(PartitionError):
            birth(source, result)

    def test_birth_strict_partition_missing_text(self):
        source = fake_source("原文。丢失。")
        result = fake_result(["原文。"])
        with pytest.raises(PartitionError):
            birth(source, result)

    def test_birth_source_reserved_key(self):
        """doc_attrs["source"] 保留键写入正确：encoding 原样、bom 为 hex 串。"""
        source = fake_source("ab", encoding="utf-16-le", bom=b"\xff\xfe")
        result = fake_result(["a", "b"], doc_attrs={"partition": "chars"})
        s = birth(source, result)
        assert s.doc_attrs["partition"] == "chars"  # 原样进入
        assert s.doc_attrs["source"] == {"encoding": "utf-16-le", "bom": "fffe"}

    def test_birth_no_bom_is_empty_string(self):
        s = birth(fake_source("a"), fake_result(["a"]))
        assert s.doc_attrs["source"] == {"encoding": "utf-8", "bom": ""}

    def test_birth_rejects_reserved_key_in_doc_attrs(self):
        source = fake_source("a")
        result = fake_result(["a"], doc_attrs={"source": {"forged": True}})
        with pytest.raises(PartitionError):
            birth(source, result)

    def test_birth_content_addressed(self):
        """相同来源与切分 ⇒ 相同 SnapshotId。"""
        a = birth(fake_source("ab"), fake_result(["a", "b"]))
        b = birth(fake_source("ab"), fake_result(["a", "b"]))
        assert a == b


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def make_snapshot(n: int = 3) -> DocumentSnapshot:
    blocks = tuple(
        Block(key=f"b{i}", content=f"段{i}。", attrs={"start": i})
        for i in range(1, n + 1)
    )
    s = DocumentSnapshot(
        id="", blocks=blocks, doc_attrs={"partition": "chars"}, key_cursor=n + 1
    )
    return replace(s, id=snapshot_id(s))


def blob_count(store: Store) -> int:
    return len(list(store.blobs_dir.glob("*.json")))


def snapshot_count(store: Store) -> int:
    return len(list(store.snapshots_dir.glob("*.json")))


class TestStoreRoundTrip:
    """验收：load(save(store, s)) == s。"""

    def test_save_load_roundtrip(self, tmp_path):
        store = Store(tmp_path / "session")
        s = make_snapshot()
        sid = save(store, s)
        assert sid == s.id
        assert load(store, sid) == s

    def test_save_returns_snapshot_id(self, tmp_path):
        store = Store(tmp_path / "session")
        s = make_snapshot()
        assert save(store, s).startswith("s-")


class TestContentAddressing:
    def test_identical_blocks_share_blob(self, tmp_path):
        """两个含相同内容块的快照共享 blob。"""
        store = Store(tmp_path / "session")
        s1 = make_snapshot()                       # b1/b2/b3 → 3 个 blob
        save(store, s1)
        assert blob_count(store) == 3
        s2 = apply(s1, (SetContent("b1", "改写"),))  # b2/b3 共享，b1 换内容
        save(store, s2)
        assert blob_count(store) == 4              # 只多 1 个 blob
        assert snapshot_count(store) == 2

    def test_blob_has_no_key(self, tmp_path):
        """blob 无 key：内容相同的块即使 key 不同也只存一份。"""
        store = Store(tmp_path / "session")
        s1 = make_snapshot()
        save(store, s1)
        for blob_file in store.blobs_dir.glob("*.json"):
            blob = json.loads(blob_file.read_text(encoding="utf-8"))
            assert set(blob) == {"content", "attrs"}

    def test_same_payload_different_key_shares_blob(self, tmp_path):
        store = Store(tmp_path / "session")
        s1 = make_snapshot(1)  # b1
        save(store, s1)
        # 另一快照：不同 key、相同 content+attrs
        twin = DocumentSnapshot(
            id="",
            blocks=(Block(key="b7", content="段1。", attrs={"start": 1}),),
            doc_attrs={"partition": "chars"},
            key_cursor=8,
        )
        twin = replace(twin, id=snapshot_id(twin))
        save(store, twin)
        assert blob_count(store) == 1

    def test_manifest_uses_refs(self, tmp_path):
        store = Store(tmp_path / "session")
        s = make_snapshot()
        save(store, s)
        manifest = json.loads(
            (store.snapshots_dir / f"{s.id}.json").read_text(encoding="utf-8")
        )
        assert manifest["spec"] == 1
        assert manifest["id"] == s.id
        for entry in manifest["blocks"]:
            assert set(entry) == {"key", "ref"}


class TestIdempotence:
    def test_repeated_save_produces_no_new_files(self, tmp_path):
        """未修改的快照重复 save 不产生新数据。"""
        store = Store(tmp_path / "session")
        s = make_snapshot()
        save(store, s)
        save(store, s)
        save(store, s)
        assert blob_count(store) == 3
        assert snapshot_count(store) == 1


class TestCurrentPointer:
    """验收：set_current(store, t) 后 current(store) == t，历史全部保留。"""

    def test_save_moves_current(self, tmp_path):
        store = Store(tmp_path / "session")
        s1 = make_snapshot()
        save(store, s1)
        assert current(store) == s1.id
        s2 = apply(s1, (Append("新", {}, at="b3"),))
        save(store, s2)
        assert current(store) == s2.id

    def test_set_current_is_rollback(self, tmp_path):
        store = Store(tmp_path / "session")
        s1 = make_snapshot()
        s2 = apply(s1, (Append("新", {}, at="b3"),))
        save(store, s1)
        save(store, s2)
        set_current(store, s1.id)          # RollBack 的物理实现
        assert current(store) == s1.id
        assert load(store, s2.id) == s2    # 目标之后的快照不删除（append-only）
        assert snapshot_count(store) == 2

    def test_current_missing_raises(self, tmp_path):
        store = Store(tmp_path / "session")
        with pytest.raises(StoreError):
            current(store)

    def test_set_current_missing_snapshot_raises(self, tmp_path):
        store = Store(tmp_path / "session")
        with pytest.raises(StoreError):
            set_current(store, "s-0000000000000000")


class TestStoreErrors:
    def test_load_missing_snapshot_raises(self, tmp_path):
        store = Store(tmp_path / "session")
        with pytest.raises(StoreError):
            load(store, "s-0000000000000000")

    def test_load_missing_blob_raises(self, tmp_path):
        store = Store(tmp_path / "session")
        s = make_snapshot()
        save(store, s)
        for blob_file in store.blobs_dir.glob("*.json"):
            blob_file.unlink()
        with pytest.raises(StoreError):
            load(store, s.id)


class TestBirthStoreIntegration:
    def test_birth_apply_save_load(self, tmp_path):
        """出生 → 迁移 → 落盘 → 装配，全链路往返相等。"""
        store = Store(tmp_path / "session")
        s1 = birth(fake_source("甲。乙。"), fake_result(["甲。", "乙。"]))
        s2 = apply(s1, (Append("丙。", {}, at="b2"),))
        save(store, s1)
        save(store, s2)
        assert load(store, s2.id) == s2
        assert "".join(b.content for b in load(store, s2.id).blocks) == "甲。乙。丙。"
        assert current(store) == s2.id

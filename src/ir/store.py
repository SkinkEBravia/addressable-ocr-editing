"""IR Store：快照的持久化、当前指针、会话目录。

对应 Docs/Design/05-ir-io.md「Store」节。

物理格式（块级内容寻址，CAS 是 store 内部实现，IR 接口不感知）：

    <session>/
      blobs/<hash>.json            # {"content": str, "attrs": Attrs}
                                   # hash = sha256(规范化 JSON)，blob 无 key
      snapshots/<SnapshotId>.json  # 清单：逻辑格式中块的 content/attrs 换为 ref
      current                      # 纯文本，内容为当前 SnapshotId

不做引用计数与 GC；保留策略是全量保留到会话结束（append-only）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .types import (
    SPEC,
    Attrs,
    Block,
    DocumentSnapshot,
    SnapshotId,
    canonical_json,
    content_id,
)


class StoreError(Exception):
    """Store 层面的失败：快照不存在、格式不支持、 blob 缺失等。"""


class Store:
    """会话目录句柄。由会话目录路径构造；目录不存在时自动创建。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    @property
    def blobs_dir(self) -> Path:
        return self.root / "blobs"

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "snapshots"

    @property
    def current_path(self) -> Path:
        return self.root / "current"

    def __repr__(self) -> str:
        return f"Store({self.root!s})"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _write_text_atomic(path: Path, text: str) -> None:
    """同目录临时文件 + os.replace，避免半截文件。"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_json_atomic(path: Path, payload: Any) -> None:
    """落盘统一用规范化 JSON（sort_keys、紧凑分隔符、UTF-8 不转义）。"""
    _write_text_atomic(path, canonical_json(payload))


def _blob_payload(block: Block) -> dict[str, Any]:
    """blob 无 key：内容相同的块即使 key 不同也只存一份。"""
    return {"content": block.content, "attrs": block.attrs}


def _blob_ref(block: Block) -> str:
    """blob 名 = sha256(规范化 JSON) 全量十六进制。"""
    return content_id(_blob_payload(block), "")


def _manifest(snapshot: DocumentSnapshot) -> dict[str, Any]:
    """快照清单：03 逻辑格式，但每个块条目为 {"key": ..., "ref": <hash>}。"""
    return {
        "spec": SPEC,
        "id": snapshot.id,
        "doc_attrs": snapshot.doc_attrs,
        "key_cursor": snapshot.key_cursor,
        "blocks": [
            {"key": b.key, "ref": _blob_ref(b)} for b in snapshot.blocks
        ],
    }


def _snapshot_path(store: Store, snapshot_id: SnapshotId) -> Path:
    return store.snapshots_dir / f"{snapshot_id}.json"


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def save(store: Store, snapshot: DocumentSnapshot) -> SnapshotId:
    """写新 blob + 写清单 + 移动 current，返回 SnapshotId。

    幂等：blob 与清单均按内容寻址，重复 save 同一快照不产生新文件。
    """
    for block in snapshot.blocks:
        path = store.blobs_dir / f"{_blob_ref(block)}.json"
        if not path.exists():
            _write_json_atomic(path, _blob_payload(block))
    manifest_path = _snapshot_path(store, snapshot.id)
    if not manifest_path.exists():
        _write_json_atomic(manifest_path, _manifest(snapshot))
    set_current(store, snapshot.id)
    return snapshot.id


def load(store: Store, snapshot_id: SnapshotId) -> DocumentSnapshot:
    """读清单并按 ref 装配 blob，对外恢复为完整 DocumentSnapshot。"""
    manifest_path = _snapshot_path(store, snapshot_id)
    if not manifest_path.exists():
        raise StoreError(f"snapshot not found: {snapshot_id!r}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("spec") != SPEC:
        raise StoreError(f"unsupported snapshot spec: {data.get('spec')!r}")
    blocks: list[Block] = []
    for entry in data["blocks"]:
        blob_path = store.blobs_dir / f"{entry['ref']}.json"
        if not blob_path.exists():
            raise StoreError(
                f"blob missing for key {entry['key']!r}: {entry['ref']}"
            )
        blob = json.loads(blob_path.read_text(encoding="utf-8"))
        blocks.append(
            Block(
                key=entry["key"],
                content=blob["content"],
                attrs=blob["attrs"],
            )
        )
    return DocumentSnapshot(
        id=data["id"],
        blocks=tuple(blocks),
        doc_attrs=data["doc_attrs"],
        key_cursor=data["key_cursor"],
    )


def current(store: Store) -> SnapshotId:
    """当前指针的唯一落盘形式：current 纯文本文件。"""
    path = store.current_path
    if not path.exists():
        raise StoreError("no current snapshot in store")
    return path.read_text(encoding="utf-8").strip()


def set_current(store: Store, snapshot_id: SnapshotId) -> None:
    """重写 current 文件，即 RollBack 的物理实现。

    目标必须是 store 中已有的快照；历史清单与 blob 全部保留（append-only）。
    """
    if not _snapshot_path(store, snapshot_id).exists():
        raise StoreError(f"snapshot not found: {snapshot_id!r}")
    _write_text_atomic(store.current_path, snapshot_id)

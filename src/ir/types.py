"""IR 数据结构：Block、DocumentSnapshot、分配器与快照的 JSON 逻辑格式。

对应 Docs/Design/03-ir-data.md。快照不可变（frozen dataclass），
`blocks` 为有序 tuple，按 `BlockKey` 寻址。

解耦约定：JSON 值约束与 partition 模块一致，但按模块边界要求在 ir 内
自行定义 `JsonValue` / `Attrs`，不 import 其他模块的内部类型。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# JSON 值约束（与 02-partition.md 的定义一致，此处为 ir 模块自己的副本）
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
"""可直接 json.dumps / json.loads 往返的值。"""

type Attrs = dict[str, JsonValue]
"""全系统元数据的统一载体。IR 只保管、不解读。"""

type BlockKey = str
"""Block 的身份。不透明字符串；同一文档内唯一、一经分配不复用。"""

HEAD: BlockKey = "head"
"""保留值：序列起点的地址（虚 Block 的 BlockKey），永远不作为真实 Block 的 key。"""

type SnapshotId = str
"""快照的身份。每次迁移产出的新快照持有新 SnapshotId。"""

SPEC = 1
"""快照持久化格式版本号。写入方总写当前版本。"""


@dataclass(frozen=True)
class Block:
    """文档层的最小寻址单位。key 只存在于此字段，不写入 attrs（单处存放）。"""

    key: BlockKey
    content: str
    attrs: Attrs


@dataclass(frozen=True)
class DocumentSnapshot:
    """文档层的状态。不可变、不持有历史、不认识会话。"""

    id: SnapshotId
    blocks: tuple[Block, ...]
    doc_attrs: Attrs
    key_cursor: int


def alloc(snapshot: DocumentSnapshot) -> tuple[BlockKey, int]:
    """分配器：取号 = f"b{key_cursor}"，返回 (新 key, 新 cursor)。

    取号时机：快照出生（为每个块坯装订 key）与 Append。
    游标随快照持久化、随迁移演进——会话中断恢复后不会重号。
    """
    return f"b{snapshot.key_cursor}", snapshot.key_cursor + 1


# ---------------------------------------------------------------------------
# 规范化 JSON 与 SnapshotId
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    """规范化 JSON：json.dumps(obj, sort_keys=True, ensure_ascii=False,
    separators=(",", ":"))。全系统唯一的内容哈希输入形式。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_id(payload: Any, prefix: str) -> str:
    """对规范化 JSON 取 SHA-256，截取前 16 个十六进制字符，加前缀。"""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:16]}"


def snapshot_to_dict(snapshot: DocumentSnapshot) -> dict[str, Any]:
    """快照的逻辑 JSON 格式（03 文档「持久化格式」节，spec 1）。

    全体成员为 str / int / JsonValue 组合，直接 json.dumps / json.loads 往返。
    """
    return {
        "spec": SPEC,
        "id": snapshot.id,
        "doc_attrs": snapshot.doc_attrs,
        "key_cursor": snapshot.key_cursor,
        "blocks": [
            {"key": b.key, "content": b.content, "attrs": b.attrs}
            for b in snapshot.blocks
        ],
    }


def snapshot_from_dict(data: dict[str, Any]) -> DocumentSnapshot:
    """从逻辑 JSON 格式还原快照。spec 不兼容或数据非法时抛 ValueError。"""
    spec = data.get("spec")
    if spec != SPEC:
        raise ValueError(f"unsupported snapshot spec: {spec!r}")
    blocks = tuple(
        Block(key=entry["key"], content=entry["content"], attrs=entry["attrs"])
        for entry in data["blocks"]
    )
    keys = [b.key for b in blocks]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate block keys in snapshot")
    if HEAD in keys:
        raise ValueError(f"reserved key {HEAD!r} used by a real block")
    return DocumentSnapshot(
        id=data["id"],
        blocks=blocks,
        doc_attrs=data["doc_attrs"],
        key_cursor=data["key_cursor"],
    )


def snapshot_dumps(snapshot: DocumentSnapshot) -> str:
    return json.dumps(snapshot_to_dict(snapshot), ensure_ascii=False)


def snapshot_loads(text: str) -> DocumentSnapshot:
    return snapshot_from_dict(json.loads(text))


def snapshot_id(snapshot: DocumentSnapshot) -> SnapshotId:
    """SnapshotId = 对快照（不含 id 字段）的逻辑格式规范化 JSON 取 SHA-256，
    加 "s-" 前缀（截取前 16 个十六进制字符）。

    分叉安全：相同内容得到相同 id；调用方传入的 id 字段不参与哈希。
    """
    payload = snapshot_to_dict(snapshot)
    del payload["id"]
    return content_id(payload, "s-")

"""块寻址文档 IR：数据结构、状态迁移、出生与持久化。

公开接口见下文 __all__；设计规格见 Docs/Design/03-ir-data.md、
04-ir-ops.md、05-ir-io.md。
"""

from .birth import (
    SOURCE_DOC_ATTR_KEY,
    BlockDraftLike,
    PartitionError,
    PartitionResultLike,
    SourceLike,
    birth,
)
from .ops import (
    ANCHOR_IS_REMOVED,
    BAD_ANCHOR,
    KEY_NOT_FOUND,
    Append,
    Op,
    OpError,
    Remove,
    SetAttrs,
    SetContent,
    apply,
)
from .store import Store, StoreError, current, load, save, set_current
from .types import (
    HEAD,
    SPEC,
    Attrs,
    Block,
    BlockKey,
    DocumentSnapshot,
    JsonValue,
    SnapshotId,
    alloc,
    canonical_json,
    snapshot_dumps,
    snapshot_from_dict,
    snapshot_id,
    snapshot_loads,
    snapshot_to_dict,
)

__all__ = [
    # types
    "JsonValue",
    "Attrs",
    "BlockKey",
    "HEAD",
    "SnapshotId",
    "SPEC",
    "Block",
    "DocumentSnapshot",
    "alloc",
    "canonical_json",
    "snapshot_id",
    "snapshot_to_dict",
    "snapshot_from_dict",
    "snapshot_dumps",
    "snapshot_loads",
    # ops
    "Op",
    "Append",
    "Remove",
    "SetContent",
    "SetAttrs",
    "OpError",
    "apply",
    "KEY_NOT_FOUND",
    "BAD_ANCHOR",
    "ANCHOR_IS_REMOVED",
    # birth
    "birth",
    "PartitionError",
    "SourceLike",
    "BlockDraftLike",
    "PartitionResultLike",
    "SOURCE_DOC_ATTR_KEY",
    # store
    "Store",
    "StoreError",
    "save",
    "load",
    "current",
    "set_current",
]

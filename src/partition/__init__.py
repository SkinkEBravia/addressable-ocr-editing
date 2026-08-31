"""partition：块生成（SourceText -> PartitionResult，严格分区）。"""

from partition.core import (
    Attrs,
    BlockDraft,
    JsonValue,
    PartitionResult,
    TextSource,
    from_json,
    partition_chars,
    to_json,
)

__all__ = [
    "JsonValue",
    "Attrs",
    "TextSource",
    "BlockDraft",
    "PartitionResult",
    "partition_chars",
    "to_json",
    "from_json",
]

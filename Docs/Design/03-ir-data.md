# 中间表示 · 数据结构

> 前置概念：[文档层](../Concepts/03-document-layer.md)；类型引用：[Attrs / JsonValue](02-partition.md#定义)

## 范围

定义 `DocumentSnapshot` 及其成员的构成、字段类型与 JSON 持久化格式。
不定义迁移语义（见 `04-ir-ops.md`），不定义出生与输出（见 `05-ir-io.md`）。

## 定义

### `BlockKey`

```text
BlockKey = str
```

Block 的身份。不透明字符串；同一文档内唯一、一经分配不复用。格式与分配策略由文档层的分配器决定，对操作语义透明。

### `HEAD`

```text
HEAD: BlockKey = "head"
```

保留值，序列起点的地址（虚 Block 的 BlockKey）。永远不作为真实 Block 的 key。

### `SnapshotId`

```text
SnapshotId = str
```

快照的身份。每次迁移产出的新快照持有新 `SnapshotId`。

### `Block`

数据接口。文档层的最小寻址单位。

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | `BlockKey` | 身份，只存在于此字段，不写入 `attrs`（单处存放） |
| `content` | `str` | 内容 |
| `attrs` | `Attrs` | 元数据，初始值来自 `BlockDraft.attrs` |

`Block = BlockKey + BlockDraft`（key 在快照出生时由分配器装订）。

### `DocumentSnapshot`

数据接口。文档层的状态。不可变、不持有历史、不认识会话。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `SnapshotId` | 快照身份 |
| `blocks` | `tuple[Block, ...]` | 有序 Block 序列，按 `BlockKey` 寻址 |
| `doc_attrs` | `Attrs` | 文档级元数据。初始值来自 `PartitionResult.doc_attrs`；不同 partition 实现留下的自定义数据都附着于此 |
| `key_cursor` | `int` | 分配器游标，见下节 |

## 分配器

```text
alloc(snapshot) -> (key = f"b{snapshot.key_cursor}", cursor + 1)
```

- 取号时机：快照出生（为每个 `BlockDraft` 装订 key）与 `Append`。
- 游标是快照的字段，随快照持久化、随迁移演进——会话中断恢复后不会重号。
- 分配策略可整体替换（如时间戳式 `YYYYMMDDHHMMSS-xxxxxxx`），调用方不得解析 key 的内容。

## 持久化格式

快照落盘为单个 JSON 文件，即权威数据；View、索引等一切下游均为派生物。

```json
{
  "spec": 1,
  "id": "s1",
  "doc_attrs": { "partition": "chars", "size": 1000 },
  "key_cursor": 3,
  "blocks": [
    { "key": "b1", "content": "……", "attrs": { "start": 0 } },
    { "key": "b2", "content": "……", "attrs": { "start": 1000 } }
  ]
}
```

规则：

- 块顺序 = `blocks` 数组顺序，不维护额外索引。
- `spec` 为格式版本号；读取方按版本做兼容升级，写入方总写当前版本。
- 全体成员为 `str` / `int` / `JsonValue` 组合，直接 `json.dumps` / `json.loads` 往返，无自定义编解码器。

## 验收

```text
json.loads(json.dumps(snapshot)) == snapshot
blocks 内 key 互不相同，且无 key == HEAD
```

## 边界

- 迁移与 RollBack 归 `04-ir-ops.md`。
- 快照如何诞生（出生接口）、如何输出（重建、View）归 `05-ir-io.md` 与 View 文档。
- `doc_attrs` 与块 `attrs` 的语义归写入方；IR 只保管、不解读。

# 中间表示 · 数据结构

> 前置概念：[文档层](../Concepts/03-document-layer.md)；类型引用：[Attrs / JsonValue](02-partition.md#定义)

## 定义

### DocumentSnapshot

`DocumentSnapshot` 表示单篇文档在某一时刻的完整状态。

| 字段           | 类型                  | 含义                 |
| -------------- | --------------------- | -------------------- |
| `id`         | `SnapshotId`        | 快照的内容标识       |
| `blocks`     | `tuple[Block, ...]` | 有序的块序列         |
| `doc_attrs`  | `Attrs`             | 文档级元数据         |
| `key_cursor` | `int`               | 下一个待分配的块编号 |

### Block

`Block` 是文档中可以独立寻址的内容单元。

| 字段        | 类型         | 含义         |
| ----------- | ------------ | ------------ |
| `key`     | `BlockKey` | 块的身份     |
| `content` | `str`      | 块的文本内容 |
| `attrs`   | `Attrs`    | 块级元数据   |

## 字段语义

### blocks：内容顺序

`DocumentSnapshot.blocks` 按文档内容的先后顺序保存 Block。块的位置由它在序列中的位置决定，块的身份由 `Block.key` 决定，两者独立。

空块序列表示空文档。

### Block.key：块身份

```text
BlockKey = str
```

同一快照内，各 Block 的 key 互不相同。修改块的内容或属性时保留 key；key的str是没有语义要求的

```text
HEAD: BlockKey = "head"
```

`HEAD` 是保留的文首锚点，不对应实际 Block，不能用作 `blocks` 中任何块的 key。

BlockKey 需要在文档与快照上下文中解释，概念定义上不提供跨文档、跨历史分支的全局身份。

### Block.content：块内容

`content` 保存块的文本内容，允许为空字符串。清空内容会保留块及其 key，删除块才会将其移出序列。初始分区不得产生空块，见 [02 的非空内容要求](02-partition.md#partitionresult)。

### Block.attrs 与 doc_attrs：元数据

`Block.attrs` 保存块级元数据，`DocumentSnapshot.doc_attrs` 保存文档级元数据，两者均使用 [02 定义的 Attrs](02-partition.md#定义)。

IR 负责保存元数据；字段的具体含义由写入方及配套消费方约定。初始块的 `attrs` 来自 `BlockDraft.attrs`，初始文档的元数据包含 `PartitionResult.doc_attrs` 及来源编码、BOM 信息。

块身份只保存在 `Block.key`，不重复写入 `attrs`。

### key_cursor：编号分配状态

当前块编号使用 `bN` 格式，`key_cursor` 保存下一个待分配的正整数编号。

初始快照包含 N 个块时，按序编号为 `b1` 至 `bN`，`key_cursor = N + 1`。初始空文档的 `key_cursor = 1`。

```python
alloc(snapshot) == (f"b{snapshot.key_cursor}", snapshot.key_cursor + 1)
```

`alloc` 是纯函数，返回新 key 和新游标，不修改输入快照。新增块后，结果快照记录新游标；删除块不回收编号。因此，沿连续向前编辑的历史，已删除的编号不会再次分配。

游标是快照状态的一部分，保存和恢复快照时一并保留。恢复旧快照也恢复旧游标，因此从旧状态继续编辑可能分配出与另一条历史分支相同的 key。

### id：快照身份

```text
SnapshotId = str
```

`id` 是完整快照状态的内容标识，不是操作编号或历史记录编号。相同完整状态按同一规则得到相同 ID；执行一次编辑不一定改变 ID。

完整状态包括块的顺序、key、content、attrs，以及 `doc_attrs` 和 `key_cursor`。正文相同但分区、元数据或游标不同，仍是不同的完整状态。

## 序列化

### 逻辑表示

快照的逻辑表示包含版本号 `spec`，以及 `DocumentSnapshot` 的全部字段。`blocks` 使用数组保存块顺序，每个块包含 `key`、`content` 和 `attrs`。

以下示例表示将 `SourceText.text == "abc\ndef"` 按每 4 个字符分区后得到的初始快照。来源编码为 UTF-8、无 BOM；`start` 是分区时输入的 `SourceText.text` 中的位置。

```json
{
  "spec": 1,
  "id": "s-9ee0bda801accd77",
  "doc_attrs": {
    "partition": "chars",
    "size": 4,
    "source": { "encoding": "utf-8", "bom": "" }
  },
  "key_cursor": 3,
  "blocks": [
    { "key": "b1", "content": "abc\n", "attrs": { "start": 0 } },
    { "key": "b2", "content": "def", "attrs": { "start": 4 } }
  ]
}
```

`spec` 是逻辑格式版本号，当前 `SPEC == 1`。读取方拒绝不支持的版本，尚无自动版本升级机制。

### 转换接口

| 接口                   | 输入                 | 输出                 |
| ---------------------- | -------------------- | -------------------- |
| `snapshot_to_dict`   | `DocumentSnapshot` | 普通 JSON 数据结构   |
| `snapshot_from_dict` | 普通 JSON 数据结构   | `DocumentSnapshot` |
| `snapshot_dumps`     | `DocumentSnapshot` | JSON 字符串          |
| `snapshot_loads`     | JSON 字符串          | `DocumentSnapshot` |

转换后的普通数据结构可以交给 `json.dumps` / `json.loads`。dataclass 快照本身不能直接交给 `json.dumps`。

### SnapshotId 的计算

`snapshot_id(snapshot)` 基于快照的逻辑表示计算 ID：

```text
payload = snapshot_to_dict(snapshot)，移除 id 字段
SnapshotId = "s-" + SHA256(UTF8(canonical_json(payload))) 的前 16 位十六进制字符
```

哈希输入包含 `spec`、有序块的 key／content／attrs、`doc_attrs` 和 `key_cursor`。传入快照的 `id` 不参与计算。

`canonical_json` 使用 `json.dumps`，参数为 `sort_keys=True`、`ensure_ascii=False`、`separators=(",", ":")`。对象字段按键排序，`blocks` 数组顺序保持不变。

## 工程约束与当前实现

### 只读约束

- 快照及其中的 Block 按只读对象使用，编辑产生结果快照，不原位修改已有状态。
- 当前 `Block` / `DocumentSnapshot` 使用 `frozen dataclass`，`blocks` 使用 tuple。这些机制限制字段重新赋值，但不会冻结元数据内部的 dict／list。
- 调用方不得原位修改 `Block.attrs`、`doc_attrs` 或其中的嵌套值。`snapshot_to_dict` 不提供深拷贝隔离，返回值中的元数据引用也须按只读方式使用。
- 深层不可变的实现保证尚未具备，后续评估记录在[清理计划](../../plan/design-cleanup.md#03-相关代码整理候选)。

### 输入校验

合法快照应满足字段类型、块 key 唯一且不使用 `HEAD`、游标可继续分配不冲突的新 key，以及 ID 与完整状态一致等约束。

- `snapshot_from_dict` 当前显式拒绝不支持的 spec、重复 BlockKey 和作为真实块 key 的 `HEAD`。
- 它尚未完整校验字段类型、`key_cursor` 有效性或 ID 与内容是否一致；dataclass 构造也不执行完整运行时校验。
- 上述检查的范围是逻辑格式反序列化入口，不能据此推断其他加载入口已提供相同保证。后续校验整理记录在[清理计划](../../plan/design-cleanup.md#03-相关代码整理候选)。

## 验收条件

对满足上述约束、ID 已由当前规则生成的合法快照：

```python
snapshot_loads(snapshot_dumps(snapshot)) == snapshot
snapshot_from_dict(snapshot_to_dict(snapshot)) == snapshot
snapshot.id == snapshot_id(snapshot)

len({b.key for b in snapshot.blocks}) == len(snapshot.blocks)
all(b.key != HEAD for b in snapshot.blocks)
```

这些条件描述合法快照应有的性质，不表示每个入口已执行全部校验。最终完整状态相同的编辑结果，不要求具有不同的 SnapshotId。

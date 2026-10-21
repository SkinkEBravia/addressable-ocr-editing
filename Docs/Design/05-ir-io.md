# 中间表示 · 出生、重建与存储

> 前置概念：[I/O 边界](../Concepts/01-io-boundary.md)；分区：[02-partition.md](02-partition.md)；快照：[03-ir-data.md](03-ir-data.md)；编辑：[04-ir-ops.md](04-ir-ops.md)

## 定义

本篇讨论初始快照的建立、从快照重建文本，以及快照的保存、加载和当前指针管理。出生与重建连接文本和快照；存储负责保留快照状态。文件路径选择、编辑表达与呈现方式不属于本篇讨论范围。

### 快照与消费方的职责

IR 对外统一提供 `DocumentSnapshot`。出生与存储接口负责快照的建立、保存、加载及当前指针管理；如何消费快照由外部模块决定。

```text
Consumer = DocumentSnapshot -> X  # 纯函数，只读快照
```

在给定配置下，消费变换是纯函数：只读快照，计算输出，不产生外部副作用。文件读写与保存时机由调用方负责。

消费方自行定义输出类型、配置、格式和业务语义。文本重建、展示或导出均由各自的消费方实现，IR 不为每种消费方式增加专用输出接口。

`reconstruction` 是独立的快照消费模块。本篇介绍重建规则，是为了说明从输入文本到快照、再到输出字节的往返契约；重建行为仍归该消费方负责。

### Store

`Store` 是快照存储目录的句柄。

| 字段 | 类型 | 含义 |
|---|---|---|
| `root` | `Path` | 存储目录，由调用方选择 |

Store 管理已保存的快照和当前快照指针，不执行编辑操作。它保存快照集合，不记录快照间的父子关系。

### 来源元数据

`doc_attrs["source"]` 是保留的文档级元数据，记录文本的字节还原信息。

| 字段 | 类型 | 含义 |
|---|---|---|
| `encoding` | `str` | `SourceText.encoding` |
| `bom` | `str` | `SourceText.bom` 的十六进制表示，无 BOM 时为空字符串 |

例如，UTF-16 LE 且带 BOM 的来源信息为：

```json
{ "source": { "encoding": "utf-16-le", "bom": "fffe" } }
```

这些字段由出生接口写入，partition 实现不得占用 `doc_attrs` 中的 `"source"` 键。

## 出生接口

```python
def birth(source: SourceText, result: PartitionResult) -> DocumentSnapshot
```

`birth` 将来源文本及其严格分区转为初始快照，不修改输入，也不写文件。

| 步骤 | 输入 | 结果 |
|---|---|---|
| 接受严格分区 | `source.text` 与 `result.blocks` | 分区满足 02 的契约 |
| 为块赋予身份 | 有序的 `BlockDraft` 序列 | 依次产生 `b1` 至 `bN`；`key_cursor = N + 1` |
| 保存元数据 | 块级 attrs、`result.doc_attrs`、来源信息 | 块级 attrs 进入各 Block；文档级 attrs 加入保留的 `source` 信息 |
| 计算身份 | 完整初始状态 | 按 03 的规则生成 `SnapshotId` |

初始空文档对应空块序列，`key_cursor = 1`。编号与内容 ID 的规则分别沿用 [03 的编号分配状态](03-ir-data.md#key_cursor编号分配状态)和 [SnapshotId 计算](03-ir-data.md#snapshotid-的计算)。

[02 的严格分区契约](02-partition.md#partitionresult)同时要求：块内容按序拼接等于原文、每块内容非空、空文本对应空块序列。违约应在产生初始快照前抛出 `PartitionError`。

当前实现检查拼接等式、非空块及文档级 source 保留键；空原文仅接受空块序列。完整入口校验已实现，见[实施计划](../../plan/design-cleanup.md#严格分区入口校验)。

## 重建接口

```python
def reconstruct(snapshot: DocumentSnapshot) -> SourceText
```

`reconstruct` 是 `reconstruction` 模块中消费快照的纯函数，只读快照，不负责写文件。

| 输出字段 | 来源 |
|---|---|
| `text` | 按 `snapshot.blocks` 顺序拼接所有 content |
| `encoding` | 来源元数据中的 encoding |
| `bom` | 来源元数据中的 bom，经 `bytes.fromhex` 还原 |

当前来源信息的读取规则为：

| 元数据情况 | 行为 |
|---|---|
| `source` 缺失或不是 dict，或 encoding 不是非空字符串 | 使用 UTF-8、无 BOM |
| encoding 为非空字符串，bom 缺失或不是字符串 | 保留 encoding，使用空 BOM |
| encoding 为非空字符串，bom 是合法十六进制字符串 | 保留 encoding，还原 BOM；空字符串还原为空字节串 |
| encoding 为非空字符串，bom 是非法十六进制字符串 | 抛出 `ValueError` |

重建不会验证 encoding 是否受支持，也不会检查它与 BOM 是否匹配；实际编码由 `sourceio.encode` 完成。

对解码策略成功接受的输入、合法分区以及来源元数据完整保留的未编辑快照，重建后再编码应逐字节还原输入。采用回退值不能恢复已经缺失的来源信息，不构成原文件字节保真的保证。

## 存储接口

```python
Store(root: str | Path)
```

调用方选择存储目录；构造 `Store` 时创建所需子目录，已有目录沿用。构造空 Store 不产生快照，也不建立当前指针。

| 接口 | 返回 | 状态影响 |
|---|---|---|
| `save(store, snapshot: DocumentSnapshot)` | `SnapshotId` | 保存快照，并将当前指针移到该快照 |
| `load(store, snapshot_id: SnapshotId)` | `DocumentSnapshot` | 加载指定快照，不移动当前指针 |
| `current(store)` | `SnapshotId` | 读取当前指针，不加载快照 |
| `set_current(store, snapshot_id: SnapshotId)` | `None` | 将当前指针移到已有快照，不创建快照 |

`save` 使用传入快照的 `id`，不重新计算身份；调用方应传入符合 03 契约的快照。`load` 对外恢复完整的 `DocumentSnapshot`，物理存储的块引用不进入快照数据结构。

## 物理格式

目录布局为：

```text
<root>/
  blobs/<ref>.json
  snapshots/<SnapshotId>.json
  current
```

### 块 blob

每个 blob 只保存块的 content 与 attrs，不保存 key。例如，03 示例中的第一个块对应：

```json
{ "content": "abc\n", "attrs": { "start": 0 } }
```

```text
ref = SHA256(UTF8(canonical_json({"content": content, "attrs": attrs})))
      的前 16 位十六进制字符
```

上述示例的 ref 为 `d971d18bae76f6fc`。`canonical_json` 使用 03 已定义的规范化规则。

content 和 attrs 均相同的块可以共享同一个 blob，即使它们的 key 不同。只有正文相同、attrs 不同的块不能按相同载荷去重。

### 快照清单

清单采用 [03 的逻辑表示](03-ir-data.md#逻辑表示)，将各块的 content 与 attrs 替换为 blob 引用，保留 key 和块顺序。03 的完整示例对应：

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
    { "key": "b1", "ref": "d971d18bae76f6fc" },
    { "key": "b2", "ref": "11a38f2be4b8448c" }
  ]
}
```

清单中的 `id` 沿用逻辑快照的内容 ID，不对物理清单另行计算 SnapshotId。`load` 按清单顺序读取引用的 blob，恢复每个 Block 的 key、content 和 attrs。

### current 文件

`current` 是纯文本文件，只保存当前 `SnapshotId`。读取当前快照需要先获取该 ID，再调用 `load`。

## 当前指针与回滚

回滚使用 `set_current(store, target)`：目标须已保存，只移动当前指针，不属于 Op，也不创建新快照。

- 切换指针不删除任何已保存的快照或 blob。
- 加载旧快照继续编辑时，使用该快照自身的 `key_cursor`；编号作用域沿用 03。
- 再次保存已有快照也会把指针移到该快照，即使无需写入新的 blob 或清单。
- 当前不做引用计数或 GC；目录何时整体清理由调用方决定。

## 工程约束与当前实现

### 输入与校验

- 出生接口实际使用 `SourceLike`、`PartitionResultLike` 和 `BlockDraftLike` 结构性输入；带有相应字段的 `SourceText`、`PartitionResult`、`BlockDraft` 满足这些输入约定，无需 IR 导入其具体实现。
- 出生时复制块级及文档级 attrs 的顶层字典；嵌套值仍可能共享引用，遵守 03 的只读约束。
- Store 的加载入口直接装配清单与 blob，不调用 `snapshot_from_dict`。当前检查清单存在、版本受支持和引用的 blob 存在；不完整校验字段类型、重复 key、保留 key、游标或内容哈希。
- `set_current` 当前检查目标清单存在，不验证其全部引用可加载；`current` 仅读取指针文件，不检查目标快照是否完整。

### 异常

| 异常 | 当前显式处理的情况 |
|---|---|
| `PartitionError` | 出生时包含空内容块、拼接不等于原文，或分区占用文档级 source 保留键 |
| `StoreError` | 所需清单、blob 或 current 文件缺失，或加载的清单版本不受支持 |
| `ValueError` | 重建遇到非法 BOM 十六进制字符串 |

文件系统异常、JSON 解析异常及非法结构造成的异常并未全部包装为 `StoreError`。

### 写入与去重

- `save` 先写缺失的 blob，再写缺失的清单，最后移动当前指针。已有同名 blob 与清单直接复用，不重写或核对内容。
- 重复保存同一合法快照不会增加 blob 或清单文件；当前指针仍会被重写。
- 每个文件使用同目录临时文件加 `os.replace` 完成替换。整个保存过程不是跨文件事务，失败可能保留已经写入的 blob 或清单，不提供整批回滚或崩溃持久性保证。
- 当前没有并发写协调机制；单文件替换不代表多写入方之间的事务保证。

校验、异常与旧注释的后续整理记录在[清理计划](../../plan/design-cleanup.md#05-相关代码整理候选)，本轮不改变行为或存储格式。

## 验收条件

对默认解码策略成功接受的字节序列 b，以及满足严格分区契约的结果：

```python
source = decode(b)
s = birth(source, partition(source))
reconstruct(s) == source
encode(reconstruct(s)) == b
```

对合法快照 s 和已经存在的目标快照 t：

```python
load(store, save(store, s)) == s
current(store) == s.id  # save 完成后

set_current(store, t.id)
current(store) == t.id
load(store, s.id) == s  # 切换指针后仍可读取已有快照
```

此外，加载快照不移动指针；重复保存不增加 blob 或清单；不同 key 但 content、attrs 相同的块共享 blob，attrs 改变则使用相应的新引用。验收以合法数据和成功完成的存储操作为前提，不表示当前入口已执行全部校验。

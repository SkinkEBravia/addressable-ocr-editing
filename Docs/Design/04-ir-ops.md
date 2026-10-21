# 中间表示 · 状态迁移（Ops）

> 前置概念：[文档层](../Concepts/03-document-layer.md)；数据结构：[03-ir-data.md](03-ir-data.md)

## 定义

本篇讨论单篇文档快照的核心编辑操作、批次执行规则和失败信息。输入为 `DocumentSnapshot` 与操作序列，输出为结果快照；历史留存、当前指针和上层编辑表达不属于本篇讨论范围。

### Op

`Op` 表示一次基本编辑。核心操作集由以下四种操作组成：

| 操作 | 参数 | 含义 |
|---|---|---|
| `Append` | `draft: BlockDraft, at: BlockKey = HEAD` | 在锚点后插入新块 |
| `Remove` | `key: BlockKey` | 删除块 |
| `SetContent` | `key: BlockKey, content: str` | 替换块内容 |
| `SetAttrs` | `key: BlockKey, attrs: Attrs` | 替换块级元数据 |

### Append

`Append` 接收 [02 定义的 BlockDraft](02-partition.md#blockdraft)，为块坯分配 key，再将新块插入到锚点之后。

| 参数 | 类型 | 含义 |
|---|---|---|
| `draft` | `BlockDraft` | 新块的内容与块级 attrs，不包含 key |
| `at` | `BlockKey` | 插入锚点，默认为 `HEAD`，表示文首 |

`BlockDraft` 是不带身份的块数据结构。非空内容要求属于初始分区契约，不是该类型自身的限制；`Append` 接收的 `draft.content` 可以为空字符串。

实现状态：Append 已接收块坯；通过 BlockDraftLike 结构性约定读取 content 与 attrs，避免核心层依赖 partition 的具体实现。调用方与测试已迁移，见[实施计划](../../plan/design-cleanup.md#append-块坯接口调整)。

## 操作语义

前置条件针对操作执行时的状态判断。

| 操作 | 前置条件 | 状态变化 | 保持不变 |
|---|---|---|---|
| `Append` | 锚点存在或为 `HEAD` | 用当前 `key_cursor` 分配新 key，游标加一；新块插在锚点之后，`HEAD` 表示文首 | 已有块的 key、content 和 attrs |
| `Remove` | key 对应真实块 | 从序列移除该块 | 其余块的 key、content 和 attrs；`key_cursor` |
| `SetContent` | key 对应真实块 | 整体替换该块的 content，允许空字符串 | 该块的 key、attrs 和位置；`key_cursor` |
| `SetAttrs` | key 对应真实块 | 整体替换该块的 attrs，合并由调用方负责 | 该块的 key、content 和位置；`key_cursor` |

四种操作均不修改 `doc_attrs`。删除块不回收编号；恢复旧快照后的编号作用域沿用 [03 的编号分配规则](03-ir-data.md#key_cursor编号分配状态)，不承诺跨历史分支永不复用。

锚点为末块时，`Append` 在尾部追加。同一锚点后连续插入时，后插入的块更靠近锚点。例如，初始块序列为 `[b1, b2]`，`key_cursor = 3`：

```text
Append(BlockDraft("甲", {}), at="b1")  → [b1, b3, b2]
Append(BlockDraft("乙", {}), at="b1")  → [b1, b4, b3, b2]
```

## apply

```python
def apply(snapshot: DocumentSnapshot, ops: tuple[Op, ...]) -> DocumentSnapshot
```

### 批次执行

- 按 `ops` 的顺序执行，后续操作看到此前操作产生的状态，包括新增块及其 key。
- 前置条件在每条操作执行时检查。例如，先删除某块再以它为插入锚点，会导致批次失败。
- 批次原子执行：任一操作失败，整批失败，不返回部分结果；输入快照保持不变。
- `apply` 不持有历史或当前指针，不执行文件读写。调用方可以用同一输入试跑，成功时丢弃结果，失败时读取错误。

### 结果快照

- 空批次返回输入快照本身，即 `apply(snapshot, ()) is snapshot`。
- 非空批次成功时返回结果快照，不修改输入快照。
- `blocks` 是按序执行全部操作后的块序列，`doc_attrs` 保持输入值。
- `key_cursor` 只因 `Append` 推进。成功批次含 N 次 `Append` 时，结果游标等于输入游标加 N；即使新增块随后被删除，已分配编号也不回收。
- 结果 ID 按 [03 的 SnapshotId 计算规则](03-ir-data.md#snapshotid-的计算)生成。成功执行不保证 ID 改变：将内容设为原值，或批次结束时完整状态与输入相同，均可得到原 ID。

输入快照与操作中的元数据遵守 [03 的只读约束](03-ir-data.md#只读约束)。当前新增块、替换块级 attrs 时会复制 attrs 的顶层字典，不提供嵌套值的深拷贝隔离。

## 错误

### OpError

`OpError` 表示核心操作的前置条件不满足，携带批次中的失败位置。

| 字段 | 类型 | 含义 |
|---|---|---|
| `index` | `int` | 失败操作在批次内的序号，从 0 开始 |
| `op` | `Op` | 失败的操作 |
| `reason` | `str` | 机器可判读的原因码 |
| `key` | `BlockKey \| None` | 涉及的 key，如有 |

| 原因码 | 触发条件 |
|---|---|
| `KEY_NOT_FOUND` | `Remove`、`SetContent` 或 `SetAttrs` 的目标不是执行时存在的真实块，包括以 `HEAD` 为目标 |
| `ANCHOR_IS_REMOVED` | `Append` 的锚点不存在，且符合当前分配策略对已分配编号的判定 |
| `BAD_ANCHOR` | `Append` 的锚点既不是 `HEAD`，也不是现存块，且不符合上述编号判定 |

当前 `ANCHOR_IS_REMOVED` 的分类依据是：缺失锚点匹配 `b<数字>`，且数字小于执行时的游标。这是基于当前编号格式的实现判定，不是通过查询删除历史得出的结论；调用方不得据此解析 BlockKey 或推断跨分支身份。

### 输入类型与实现边界

- 当前实现遇到不能识别的操作类型时抛出 `TypeError`，不包装为 `OpError`；批次同样不返回部分结果。
- `apply` 以输入快照和操作字段满足类型约束为前提，不承担完整的运行时类型及元数据可序列化性校验。不能把所有非法输入造成的异常都视为 `OpError`。

## 验收条件

对合法快照和合法操作字段，应满足：

```text
apply(s, ()) is s
相同 s 与 ops 重复执行，结果相等
成功或失败均不修改输入 s
任一操作失败 ⇒ 不返回部分结果
失败的 OpError.index 对应原批次中从 0 开始的操作位置
成功结果的 doc_attrs == s.doc_attrs
成功结果的 key_cursor == s.key_cursor + 批次中 Append 的数量
成功结果的 id == snapshot_id(成功结果)
```

此外，后续操作应能引用同批次此前新增的块；同一锚点连续插入的结果顺序应符合本篇示例。将已有块的内容设为原值时，结果快照 ID 与输入相同。

# 块生成（Partition）

> 前置概念：[严格分区](../Concepts/02-partition.md)、[文档层](../Concepts/03-document-layer.md)

## 范围

```text
SourceText -> tuple[BlockDraft, ...] + 文档级 attrs
```

块生成把全文切成内容切片，并产出元数据。它**不分配 BlockKey**——key 由文档层在快照出生时装订；也**不认识 IR**，只对本节定义的输出契约负责。

模块边界就是接口本身：内部实现自由，切分（分块）与元数据提取（describe）允许耦合，不做强制分离。

## 定义

### `JsonValue`

```text
JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
```

### `Attrs`

```text
Attrs = dict[str, JsonValue]
```

全系统元数据的统一载体。块级 attrs、文档级 attrs、IR 中 Block 附着的 attrs、快照附着的自定义数据，都是这一个类型。

### `BlockDraft`

无 key 的块坯。`Block = BlockKey + BlockDraft`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | `str` | 内容切片 |
| `attrs` | `Attrs` | 块级元数据，内容由产生它的 partition 实现自行定义 |

## 接口

```python
def partition(source: SourceText) -> PartitionResult
```

### `PartitionResult`

数据接口。

| 字段 | 类型 | 说明 |
|---|---|---|
| `blocks` | `tuple[BlockDraft, ...]` | 有序块序列 |
| `doc_attrs` | `Attrs` | 文档级元数据 |

**契约（严格分区）**：以下条件同时成立。

```text
concat(d.content for d in blocks) == source.text
每个 d.content 非空
source.text == "" 时，blocks == ()
```

空文本是边界情况：空块序列的拼接仍为原文，不是拼接等式的例外。非空原文对应至少一个块；空白行包含换行符，不属于空内容块。

工程校验与实现状态：

- partition 实现负责产出符合上述契约的结果；进入 IR 时由 `birth` 校验，失败抛出 `PartitionError`。
- 当前内置的 chars / lines 分区满足完整契约；`birth` 只校验拼接等式，尚未拒绝自定义分区中的空内容块。
- 完整入口校验需要实现，列入[设计清理计划](../../plan/design-cleanup.md#待实现的严格分区入口校验)；本轮只更新设计，不修改代码。
- 非空要求约束初始分区，不据此禁止后续编辑将已有 Block 的内容设为空。

## 行为规则

- 只读取 `source.text`；不读文件、不做编码判断。
- 不改写文本内容；规整归 `transforms/`。
- 内部结构自由：允许按文档结构（如 Markdown 语法）同时完成切分与元数据写入。
- attrs 中只允许出现 `JsonValue`。
- 文档级 attrs 的 `"source"` 是出生接口的保留键，partition 实现不得占用；编码与 BOM 由 `birth` 写入，见 [05-ir-io.md](05-ir-io.md#出生接口)。

## 参考实现：按字符切分

```python
def partition_chars(source: SourceText, size: int) -> PartitionResult
```

- 每 `size` 个字符切一块，最后一块允许短于 `size`。
- `size` / `start` 使用 Python `str` 的索引单位，不按字节、词或可见字形计数；`size` 必须是正整数。
- 每块 attrs：`{"start": <int>}`，即该块在分区时输入的 `SourceText.text` 中的起始位置。
- doc_attrs：`{"partition": "chars", "size": size}`。

## 参考实现：按行切分

```python
def partition_lines(source: SourceText) -> PartitionResult
```

- 按行切分（`str.splitlines(keepends=True)` 语义），行终止符归属其所在块。
- 每块 attrs：`{"start": <int>, "line": <int>}`，分别为该块在分区时输入的 `SourceText.text` 中的起始位置与 0 起的行号。
- doc_attrs：`{"partition": "lines"}`。
- 适用：错误按行分布的文本（如 OCR 输出），使 `set_content` 的整块替换成本最小化。

两种参考实现的位置 attrs 都描述分区时输入的 `SourceText.text`。编辑后不会自动更新，不能默认用它们定位后续快照的当前位置；Agent 的寻址身份由 View 的 ID 策略另行提供。

## 持久化

- `PartitionResult` 可转换为仅含普通 JSON 值的结构；当前 `to_json` / `from_json` 负责块序列及 attrs 的结构转换，并保证往返相等。
- dataclass 对象本身不能直接传给 `json.dumps`；结构转换后不需要自定义 JSON 编码器。
- 落盘的时机与位置归装配层（会话目录）；partition 本身无状态、不落盘。

## 验收

```text
concat(blocks[*].content) == source.text
all(block.content != "" for block in blocks)
source.text == "" ⇒ blocks == ()
from_json(to_json(result)) == result
```

## 边界

- 不分配 `BlockKey`，不感知 `Block`、快照与迁移。
- 结构 attrs 的语义归产生它的 partition 实现所有；IR 与通用 Presenter 不解释这些字段。
- 与 partitioner 配套的专用 Agent ID strategy 可以依赖约定的 attrs 字段，配套关系由装配层选择，见 [06-view.md](06-view.md#策略与-partition-的配套)。

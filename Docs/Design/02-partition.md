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

**契约（严格分区）**：

```text
concat(d.content for d in blocks) == source.text
```

空文本对应空 `blocks`（严格分区的唯一例外）。

## 行为规则

- 只读取 `source.text`；不读文件、不做编码判断。
- 不改写文本内容；规整归 `transforms/`。
- 内部结构自由：允许按文档结构（如 Markdown 语法）同时完成切分与元数据写入。
- attrs 中只允许出现 `JsonValue`。

## 参考实现：按字数切分

```python
def partition_chars(source: SourceText, size: int) -> PartitionResult
```

- 每 `size` 个字符切一块，最后一块允许短于 `size`。
- 每块 attrs：`{"start": <int>}`，即该块在全文中的起始字符偏移。
- doc_attrs：`{"partition": "chars", "size": size}`。

## 参考实现：按行切分

```python
def partition_lines(source: SourceText) -> PartitionResult
```

- 按行切分（`str.splitlines(keepends=True)` 语义），行终止符归属其所在块。
- 每块 attrs：`{"start": <int>, "line": <int>}`，分别为起始字符偏移与 0 起的行号。
- doc_attrs：`{"partition": "lines"}`。
- 适用：错误按行分布的文本（如 OCR 输出），使 `set_content` 的整块替换成本最小化。

## 持久化

- `PartitionResult` 全体成员均为 `str` / `JsonValue` 组合，可直接 `json.dumps` 序列化、无损还原，无需自定义编解码器。
- 落盘的时机与位置归装配层（会话目录）；partition 本身无状态、不落盘。

## 验收

```text
concat(blocks[*].content) == source.text
json 序列化 -> 反序列化 == 原 PartitionResult
```

## 边界

- 不分配 `BlockKey`，不感知 `Block`、快照与迁移。
- attrs 的语义归产生它的 partition 实现所有；下游（IR、View）不得假设 attrs 中存在特定字段。

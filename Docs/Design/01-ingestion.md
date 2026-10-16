# 数据摄入

> 前置概念：[I/O 边界与无损保真](../Concepts/01-io-boundary.md)

## 范围

```
bytes ↔ SourceText
```

数据摄入模块 `sourceio` 承担文件级保真的全部责任：`bytes ↔ SourceText`。
不感知分区、块、文档层；不持有状态，文件路径由装配层传入。

## 定义

### `SourceText`

数据接口。一份文件的文本级表示，携带无损回写所需的全部元数据。

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | `str` | 全文。换行符原样保留（`\r\n` / `\r` / `\n` 不做转换） |
| `encoding` | `str` | 解码所用编码，如 `"utf-8"`、`"utf-16-le"` |
| `bom` | `bytes` | 原文件的 BOM 字节，无 BOM 时为 `b""` |

### 无损（lossless）

对当前解码策略成功接受的输入，仅指逐字节相等：

```text
encode(decode(b)) == b
```

任何其他等价关系不叫无损。

## 接口

```python
def decode(raw: bytes) -> SourceText
def encode(source: SourceText) -> bytes

def read(path: Path) -> SourceText    # 二进制读文件 + decode
def write(path: Path, source: SourceText) -> None  # encode + 二进制写文件
```

`decode` / `encode` 为纯函数；`read` / `write` 是文件 I/O 包装，不引入额外语义。

## 行为规则

### 默认解码策略（当前实现）

默认使用默认解码策略，当前 `decode` / `read` 均使用以下规则：

1. 检测 UTF-8 / UTF-16 LE / UTF-16 BE 的 BOM。命中则将 BOM 单独记入 `bom`，正文分别按 `utf-8` / `utf-16-le` / `utf-16-be` 严格解码，BOM 不进入 `text`。UTF-8 BOM 输入的 `encoding` 为 `"utf-8"`，不是 `"utf-8-sig"`，避免回写时重复生成 BOM。
2. 无 BOM 则按 UTF-8 严格解码，`bom = b""`。
3. 解码失败抛出 `DecodeError`，不做编码猜测、不替换非法字节。

### encode

1. `text` 按 `encoding` 编码，前部拼接 `bom`。
2. 不做换行规范化、不做 Unicode 规整、不追加末尾换行。

### read / write

- 必须以二进制模式打开文件，禁用隐式换行转换。

## 验收

以下等式针对默认解码策略成功接受的字节序列；不支持或非法的输入通过 `DecodeError` 拒绝。

```text
write(path, read(path)) 后，文件内容逐字节不变
encode(decode(b)) == b
```

## 边界

- 允许进入核心流的只有上述操作；空白折叠、格式化等规整属于 `transforms/`，默认不得介入。
- `SourceText` 是本模块唯一的对外类型；下游模块不得直接读文件。

## 扩展解码策略（未来设计，当前不实现）

未来按文件扩展名调取对应解码器；未配置扩展解码器的扩展名使用默认解码策略。

```text
文件路径 → 扩展名 → 选择对应解码器；无对应解码器 → 默认解码策略
文件 bytes → 所选解码器 → SourceText
```

- 扩展名用于选择解码策略；具体文本编码及 BOM 由所选解码器处理，并写入 `SourceText`。
- 每个解码器对成功接受的输入仍须满足字节级往返保真；拒绝的输入不属于该等式的定义域。
- 文件路径不加入 `SourceText`，不交给 partition 或 IR 解释。
- 当前没有扩展名路由或扩展解码器注册机制，本轮不增加接口或实现。

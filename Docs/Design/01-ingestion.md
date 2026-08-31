# 数据摄入

> 前置概念：[I/O 边界与无损保真](../Concepts/01-io-boundary.md)

## 范围

```
File(bytes) -> SourceText
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

仅指逐字节相等：

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

### decode

1. 检测 BOM：`utf-8-sig` / `utf-16-le` / `utf-16-be`。命中则按对应编码解码，BOM 字节记入 `bom`，不进入 `text`。
2. 无 BOM 则按 UTF-8 严格解码，`bom = b""`。
3. 解码失败抛出 `DecodeError`，不做编码猜测、不替换非法字节。

### encode

1. `text` 按 `encoding` 编码，前部拼接 `bom`。
2. 不做换行规范化、不做 Unicode 规整、不追加末尾换行。

### read / write

- 必须以二进制模式打开文件，禁用隐式换行转换。

## 验收

```text
write(path, read(path)) 后，文件内容逐字节不变
encode(decode(b)) == b
```

## 边界

- 允许进入核心流的只有上述操作；空白折叠、格式化等规整属于 `transforms/`，默认不得介入。
- `SourceText` 是本模块唯一的对外类型；下游模块不得直接读文件。

## 扩展

新增编码支持 = 在检测链末尾、`DecodeError` 之前插入一条严格解码规则：

```text
BOM → UTF-8 → <新编码> → DecodeError
```

条件只有一个：该编码对合法字节序列往返无损（decode 后再 encode 逐字节相等）。`encode` 与 `SourceText` 不需要改动。

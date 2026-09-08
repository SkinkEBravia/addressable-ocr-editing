# 视图（View）

> 前置概念：[View 与 Agent 操作面](../Concepts/04-view.md)；统一输出接口：[05-ir-io.md](05-ir-io.md#统一输出接口)

## 范围

快照的消费方之一：`DocumentSnapshot -> View`。
定义 `View`、`Presenter`、`AgentView`、`ReferenceMap`、`AgentBlockId` 策略与标注形式。
不定义 patch 方言与解析（见 `07-agent-api.md`）。

## 定义

### `View`

数据接口。从快照导出的对象，服务于特定目的。

| 字段 | 类型 | 说明 |
|---|---|---|
| `view_id` | `ViewId` (`str`) | View 的身份，由 Presenter 分配 |
| `snapshot_id` | `SnapshotId` | 来源快照 |
| `payload` | `JsonValue` | 展示内容 |
| `render_spec` | `Attrs` | 导出元数据（策略名、标注形式名等） |

### `AgentView`

`View` 的一种，服务 Agent。`payload` 为插入了 ID 标注的还原文本；分块方式与快照一致，但使用另一套 ID——`AgentBlockId`。

### `ReferenceMap`

```text
ReferenceMap = dict[AgentBlockId, BlockKey]
```

双射。随 `AgentView` 一起产出，覆盖快照的全部 `blocks`。patch 降解时经它把 `AgentBlockId` 换回 `BlockKey`。

### `AgentIdStrategy`

```python
AgentIdStrategy = (block: Block, index: int) -> AgentBlockId  # str
```

决定 Agent 看到的块 ID 长什么样。规则：

- 输入包含整个 `Block`——**允许读取 `attrs`**，即策略可以依赖 partition 写入的元数据。例：md 配套的 ID 策略用标题结构信息生成 `title1-paragraph1` 式 ID。
- 同一快照内生成的 `AgentBlockId` 必须互不相同（否则双射不成立，`present` 抛 `ViewError`）。
- 同一 `(snapshot, strategy, annotator)` 的 `payload` 与 `ReferenceMap` 必须确定。

### `Annotator`

```python
Annotator = (agent_id: AgentBlockId, content: str) -> str
```

标记形式：把一块内容包装成带 ID 标注的文本。与 id 策略相互独立（标记形式与 id 策略是两件事），由 Presenter 组合使用。

### 策略与 partition 的配套

策略对 attrs 的依赖构成与 partition 实现的**配套关系**（如 md partition ↔ md ID 策略）。配套不由本模块约束：IR 不感知策略，partition 不感知 ID。配对由装配层在选择"用哪个 partition + 用哪个策略"时完成。

已交付的配套：

| partition | id 策略 | 标注形式 | 用途 |
|---|---|---|---|
| 任意 | `blockkey_as_is`（AgentBlockId = BlockKey） | `xml_ish`（`<x id="bN"\>`） | patch 操作面（07 默认栈） |
| `partition_lines`（每行一块） | `line_number`（AgentBlockId = 行号，1 起，位置性） | `cat_n`（`N: content`） | 行号锚操作面（swe_edit） |
| 任意 | `prefixed_blockkey`（`AgentBlockId = <prefix>:<BlockKey>`，如 `c0:b1`） | `xml_ish` | **全局作用域**操作面（`*_global_seq`）：跨 chunk 寻址需要命名空间隔离 |
| `partition_lines` | `numkey`（AgentBlockId = BlockKey 序号，`b12` → `12`；**稳定**，编辑后不重排） | `cat_n` | num-key 锚操作面（neo 实验2：`patch_find_replace` / `find_replace_numkey` 等） |
| `partition_lines` | —（不寻址） | `plain`（恒等，无标注） | path 抬头 + 纯原文视图（neo 实验1：`*_anthropic_style`） |

## 接口

```python
def present(snapshot: DocumentSnapshot, strategy: AgentIdStrategy, annotator: Annotator) -> AgentView

def present_file(snapshot: DocumentSnapshot, filename: str,
                 prefix: str | None = None,
                 annotator: Annotator | None = None,
                 strategy: AgentIdStrategy | None = None,
                 label: str = "File") -> AgentView
```

`present_file` 是 `present` 的**带命名空间变体**，服务于一次对话内呈现多个单元的场景：

- payload 前置文件标识抬头 `--- [{label}: {filename}] ---`；
- 给定 `prefix` 时，`AgentBlockId` 走 `prefixed_blockkey`（`c0:b1`），使**不同单元的块 id 不相撞**；
- 这是**全局作用域**（跨 chunk 回溯编辑）成立的前提：没有命名空间，`b1` 会同时指向多个单元的首块。

`prefix = None` 时退化为 `present` 的行为加一个抬头。显式给 `strategy` 时优先于
`prefix`（如 num-key 视图：`strategy=numkey, annotator=cat_n`）；`label` 只改抬头用词
（默认 `File`，非文件语义的处理对象用 `Text`）。

Presenter 是统一输出接口的消费方，纯函数、无副作用、不改动快照。
`payload` = 按序对每个块应用 `annotator(strategy(block, i), block.content)` 并拼接。

同一 `(strategy, annotator)` 组合也可渲染快照的任意子集（如 patch 后的受影响块），渲染结果与全量 View 中的对应片段一致。

## 失效

`AgentView` 与 `ReferenceMap` 只对 `snapshot_id` 标明的快照有效。快照迁移后旧 View 失效，须重新 `present`；使用过期的 `AgentBlockId` 属于调用方错误。

## 验收

```text
reference_map 为双射且覆盖全部 blocks
同一 (snapshot, strategy, annotator) 重复 present，payload 与 reference_map 相同
```

## 边界

- 不定义 patch 方言、解析与降解（`07-agent-api.md`）。
- 不产生除 `AgentView` 外的任何输出；不落盘。

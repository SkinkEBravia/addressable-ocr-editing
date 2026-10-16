# 总览

## 目的

把文本表示为可寻址、可编辑、可重建的文档状态，供 Agent 通过不同编辑接口操作。

本篇描述概念、数据流和职责边界；具体接口与执行规则见各设计文档。

## 全链路

### 输入链路

| 输入 | 逻辑变换 | 输出 |
|---|---|---|
| 文件 bytes | 解码，保留编码与 BOM | `SourceText`：文本及字节还原信息 |
| `SourceText` | 严格分区，描述文档与块的结构 | `PartitionResult`：有序 `BlockDraft` 序列及文档级 attrs；每个块坯包含 content 与块级 attrs |
| `SourceText` + `PartitionResult` | 为块赋予 `BlockKey`，建立初始文档状态 | `DocumentSnapshot` |

严格分区的含义是：每块内容非空，块内容按序拼接恰好得到输入文本；空文本对应空块序列。完整契约见 [02-partition.md](02-partition.md#partitionresult)。

```text
s = decode(bytes)
r = partition(s)
concat(d.content for d in r.blocks) == s.text
S = birth(s, r)
```

输入链路不改变文本内容。attrs 描述结构，不代替正文；`BlockKey` 在文档出生时分配，不由 partition 产生。

工程约束：

- `birth` 当前检查拼接等式；完整严格分区入口校验还须拒绝空内容块，已列入[设计清理计划](../../plan/design-cleanup.md#待实现的严格分区入口校验)，本轮不改代码。
- `birth` 保存 `SourceText` 的编码与 BOM；对应的 `source` 元数据键为保留键。
- 文件读取、分区结果落盘和会话目录管理由各自的调用方负责。

### 输出链路

IR 对外提供 `DocumentSnapshot`。重建和呈现是两个独立的快照消费方向。

| 输入 | 逻辑变换 | 输出 |
|---|---|---|
| `DocumentSnapshot` | 按文档顺序拼接块内容，取回字节还原信息 | `SourceText` |
| `SourceText` | 按指定编码与 BOM 编码 | 文件 bytes |
| `DocumentSnapshot` + ID 策略 + 标注形式 | 呈现文档，建立 Agent 地址与块身份的映射 | `AgentView`：展示文本、来源快照、`ReferenceMap` 等 |

对于合法输入，未经编辑的输入链路与文件输出链路满足字节级保真：

```text
s = decode(b)
r = partition(s)
S = birth(s, r)

reconstruct(S) == s
encode(reconstruct(S)) == b
```

- 文件路径只决定从哪里读、向哪里写，不参与上述等式。
- View 中的标注不属于正文，View 不承担字节还原职责。
- 编辑后的输出反映新文档状态，不要求与原文件字节相同。

### 编辑链路

以下是按块寻址的 surface patch 链路。其他 Agent 编辑接口如何接入，见装配章节。

| 输入 | 逻辑变换 | 输出 |
|---|---|---|
| Agent 编辑表达 | 按方言解析 | `SurfaceOp` 序列 |
| `SurfaceOp` 序列 + `ReferenceMap` + 当前快照 | 将 Agent 地址映射为块身份，将复杂操作展开为基本操作 | `CoreOp` 序列 |
| 当前快照 + `CoreOp` 序列 | 执行文档状态迁移 | 结果快照 |

```text
surface_ops = parse(edit_text)
core_ops = degrade(surface_ops, reference_map, S)
S' = apply(S, core_ops)
```

工程约束：

- 地址映射对应产生它的快照；调用方负责选择正确的 View 与当前状态。
- `apply` 对一批基本操作原子执行，失败不改变输入快照。
- 降解保留操作来源，供错误定位；成功后的受影响块可重新渲染为回执。
- 编辑语义与保存时机分离：状态迁移产生快照，调用方决定何时提交 Store。

## 附加信息

### 文档状态机与快照操作集

文档状态为 `DocumentSnapshot`。当前结构是有序 Block 序列；每个 Block 包含 `BlockKey`、content 和 attrs。

核心迁移操作只有四种：

| 操作 | 状态变化 |
|---|---|
| `Append(draft, at)` | 分配新块身份，在锚点后插入块；`HEAD` 表示文首 |
| `Remove(key)` | 移除对应块 |
| `SetContent(key, content)` | 替换对应块的内容 |
| `SetAttrs(key, attrs)` | 替换对应块的 attrs |

- 快照不持有历史，也不认识会话；Store 保存快照与当前指针。
- `birth` 建立初始快照；`apply` 计算迁移结果。`SnapshotId` 由快照内容决定，空操作批次返回原快照。
- rollback 将当前指针切换到已有快照，不属于 `CoreOp`，不创建新快照。
- move、merge、replace 等复杂语义在上层展开，不扩大核心操作集。
- 当前契约围绕序列建立。树／图结构是后续演进方向，本轮清理不引入新结构或操作。

### 元数据与身份

| 概念 | 归属与用途 |
|---|---|
| 块级／文档级 attrs | partition 可产生结构描述；IR 保存这些信息，具体语义由产生者与配套消费方约定 |
| 编码与 BOM | `sourceio` 获取，`birth` 写入文档元数据，重建时取回 |
| 文件路径／展示名称 | 装配层提供；当前 CLI 将源文件路径保存到会话元数据，Presenter 可接收展示名称 |
| `BlockKey` | IR 中块的身份；由文档层分配 |
| `AgentBlockId` | Agent 可见地址；由 View 的 ID 策略产生，经 `ReferenceMap` 映射到 `BlockKey` |

Markdown 专用 partitioner 可将标题层级等结构写入 attrs，配套的 Agent ID strategy 可读取这些信息。两者的配套关系由装配层选择；这是扩展方向，当前没有 Markdown 专用实现。

## 装配

装配选择组件并驱动链路，不是输入、输出、编辑链路末尾的一个固定步骤。

### 职责与边界

| 层／入口 | 职责 | 当前模块 |
|---|---|---|
| 文档核心 | 解码、分区、快照、基本迁移、持久化、重建 | `sourceio`、`partition`、`ir`、`reconstruction` |
| 呈现与编辑语义 | View、地址映射、patch 解析与复杂操作降解 | `view`、`surface` |
| Agent 工具配置与运行时 | 组合呈现、方言、执行和输出提取；驱动 Session、反馈与预算 | `agent`，调用 `llm` |
| 文件操作入口 | 选择组件，管理文件路径与会话，驱动 ingest／view／patch／write／rollback | `application` |
| 实验入口 | 组合数据集、工具配置、模型配置与执行预算，保存磁带并评分 | `experiment`，调用 `datasetkit` 与数据集契约 |

- 组件只经公开契约交互；上层可以消费公开数据类型，不依赖下层内部实现。
- 装配层选择 partition、ID 策略、标注形式与编辑方言；块身份和快照身份仍由文档层产生。
- `surface` 提供通用块 patch 语义；不同工具配置通过 `ToolSet` 契约接入 Agent 运行时。
- 普通 rewrite 直接从模型响应提取 `SourceText`，不必经过 IR；IR-backed 工具从快照重建输出。
- 文件入口通过 `sourceio` 获取 `SourceText`；实验入口从数据集获得任务文本。字节往返契约针对文件链路，不能直接外推为所有实验工具的输出保证。

### 后续清理重点

当前扩展主要集中在 Agent 工具配置与装配入口。清理时优先检查：

- 工具配置之间重复的 IR 初始化、逐行调用解析和轮末持久化逻辑。
- 工具私有状态、编辑语义、呈现策略与保存时机是否混杂；复用时保留各配置的真实行为差异。
- CLI 与实验入口的组件选择和默认值差异，明确哪些是用途差异、哪些是历史遗留。
- 历史工具名与磁带兼容关系；不能仅因旧命名或当前实验未使用就删除。

本轮只整理已有职责和行为。代码删除与合并先列清单，确认后执行；不借清理增加功能。

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-ingestion.md](01-ingestion.md) | bytes 与 `SourceText` 的保真边界 |
| [02-partition.md](02-partition.md) | 严格分区、`BlockDraft` 与 attrs |
| [03-ir-data.md](03-ir-data.md) | 块身份、快照数据结构与逻辑格式 |
| [04-ir-ops.md](04-ir-ops.md) | 核心状态迁移与复杂语义展开 |
| [05-ir-io.md](05-ir-io.md) | 快照出生、重建与 Store |
| [06-view.md](06-view.md) | View、ID 策略、标注与地址映射 |
| [07-agent-api.md](07-agent-api.md) | SurfaceOps、patch 方言、降解与回执 |
| [08-llm.md](08-llm.md) | 模型访问与协议适配 |
| [09-tools.md](09-tools.md) | ToolSet、Session 与 Agent loop |
| [10-datasets.md](10-datasets.md) | 数据集与评测契约 |
| [11-experiment.md](11-experiment.md) | 实验装配、磁带、replay 与报告 |

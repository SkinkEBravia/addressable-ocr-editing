# 数据流

## 目的

给 Agent 分块操作文档的能力：文本文件拆进 IR，产出 Agent 看的 View，按块编辑，最后还原回文件。

## 全链路

```text
[数据摄入]                                    // 01-ingestion.md
File(bytes) -> SourceText

[块生成]                                      // 02-partition.md
SourceText -> tuple[BlockDraft, ...] + 文档级 attrs

[中间表示.出生]                               // 05-ir-io.md
tuple[BlockDraft, ...] + 文档级 attrs -birth(装订BlockKey)-> DocumentSnapshot

[中间表示.输出]                               // 05 统一输出接口：快照即唯一输出
DocumentSnapshot -> reconstruct -> SourceText -> file   // 消费方：还原到文件
DocumentSnapshot -> present -> View                     // 消费方：视图，06-view.md
...                                                     // 其他消费方（transforms 等）

[中间表示.状态转移]                           // 04-ir-ops.md
DocumentSnapshot -apply(ops)-> new DocumentSnapshot
rollback(SnapshotId)                            // 移动 store 指针，不产生新快照

[Agent接口]                                   // 07-agent-api.md
Agent_patch -> parse -> surface ops -> degrade -> ops
patch 成功返回 PatchResult（新快照 + 受影响块的标注渲染）
```

## 装配层职责

装配层驱动上面整条链，并持有链上没有主人的东西：

- 文件路径与会话目录（CLI 把链路摊到多个进程上，状态经会话目录落盘共享）
- store 与当前指针的初始化
- 组件配套的选择：partition ↔ id 策略 ↔ 标注形式 ↔ patch 方言

BlockKey 归文档层的分配器（随快照持久化的游标）；SnapshotId 是快照内容哈希，由 `apply` / `birth` 生成。两者都不需要装配层分配。

## 验收：三条保真

```text
io      write(read(b)) == b
切片    concat_segments(materialize(s, plan)) == s.text
IR 重建 reconstruct(build(blocks)) == s.text
```

三条合成一条端到端等式：一份文件 ingest 之后不做任何编辑直接写出，与原文件逐字节相同。

## 解耦

模块之间只经各自定义自己的接口，不共享内部类型。

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-ingestion.md](01-ingestion.md) | 数据摄入：bytes ↔ SourceText |
| [02-partition.md](02-partition.md) | 块生成：严格分区、Attrs、BlockDraft |
| [03-ir-data.md](03-ir-data.md) | IR 数据结构与持久化格式 |
| [04-ir-ops.md](04-ir-ops.md) | 状态迁移：核心 op、apply、OpError、RollBack |
| [05-ir-io.md](05-ir-io.md) | 出生、统一输出接口、store（CAS）与会话 |
| [06-view.md](06-view.md) | View、AgentId 策略、标注形式 |
| [07-agent-api.md](07-agent-api.md) | SurfaceOp 标准集、错误回传、默认组件、CLI |
| [08-llm.md](08-llm.md) | LLM 客户端：协议适配、凭证、采样参数、对话 |
| [09-tools.md](09-tools.md) | 工具配置、agent loop、外部 harness 驱动 |
| [10-datasets.md](10-datasets.md) | dataset.py 契约、评测、evalkit、测试入口 |
| [11-experiment.md](11-experiment.md) | 实验装配：执行矩阵、对话录、replay、报告 |

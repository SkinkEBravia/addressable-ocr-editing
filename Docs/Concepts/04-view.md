# 概念：View 与 Agent 操作面

> **定义 View**
>
> View 是从文档快照导出的一个对象，服务于特定目的。每个 View 有一个标明身份的唯一 `ViewId`，并存储其来源的 `SnapshotId`。`payload` 是这个视图展示的内容，附有 `render_spec` 记录导出相关的元数据。

> **定义 AgentView**
>
> 专门服务于 Agent 的一种文本视图。其 `payload` 按快照中的块顺序生成，是否显示 ID 标注由标注形式决定。Agent 侧地址称为 `AgentBlockId`，通过双射 `ReferenceMap` 与 `BlockKey` 联系；它的值也可以直接采用 BlockKey。无标注的展示仍可携带该映射。地址映射支持 Agent 按所选 ID 策略操作 Block。

同一个快照可以有不同的视图、不同的 `AgentBlockId` 策略。View 通过 `Presenter` 产生。

> **定义 Agent 操作面**
>
> Agent 用一段文本表达一批编辑，按 `AgentBlockId` 寻址。这段文本经解析器变成与方言无关的 surface 操作序列，再降解为文档层的核心操作。核心操作集之外的 surface 语义（如拆块、并块）在降解时展开，不进入文档层。

两个可替换点，互不影响：

- **AgentId 策略**——决定块的 id 长什么样。可以是简单计数，也可以结合生成器（如 md 生成器配套 md ID 策略）。
- **patch 方言**——决定 Agent 怎么写这批编辑。可以是 fn 形式，也可以是类 JSON。换方言只换解析器。

标记形式与 id 策略是两件事：比较 id 策略时标记形式必须不变，否则两个变量混在一起。

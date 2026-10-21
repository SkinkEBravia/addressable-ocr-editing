# 概念：文档层

> **定义 `Block`**
>
> Block 是文档层的最小寻址单位，由 BlockKey、content 与 attrs 构成。BlockKey 是它的身份。

> **定义 文档层**
>
> 文档层的一篇文档是一个状态机：状态是不可变快照，迁移是可逆的受控操作。
>
> 快照持有一个有序 Block 序列，按 BlockKey 寻址；头部被称作 Head，是特别的地址，可以认为是虚 Block 的 BlockKey。快照不可变、不持有历史、不认识会话。有 `SnapshotId` 决定每一个快照的身份。
>
> 迁移只能来自一个封闭的核心操作集。每次迁移产出一个新快照。核心操作集之外的语义不属于文档层迁移。
>
> 文档层不定义快照如何诞生，也不定义快照如何输出。两者各由一个接口承担。

`BlockDraft` 表示尚未分配 BlockKey 的块坯，仅包含 content 与 attrs。

状态迁移操作集：

- `Append(BlockDraft, at)` —— 为块坯分配 BlockKey，插入到锚点 `at` 之后，`at ∈ BlockKey ∪ {Head}`
- `Remove(BlockKey)`
- `SetContent(BlockKey, content)`
- `SetAttrs(BlockKey, attrs)`

在此之上追加 RollBack：可回滚到任意快照。撤销不依赖逆操作，由快照的留存与指针移动承担。

第一版只实现文档层；其上的工作区层（文件夹结构）见 `workspace_design.md`，暂不实现。

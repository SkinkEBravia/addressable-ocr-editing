# 任务：View 层上下文管理（省略式视图）的文献调研 + Gap 分析

日期：2026-09-04
仓库：Batch-Doc-Process-V2（HIPE-OCRepair-2026 / 操作面研究）

## 背景锚点（来自仓库）
- IR：`DocumentSnapshot = blocks(BlockKey, content, attrs) + doc_attrs`（Docs/Design/03-ir-data.md）
- View：`present(snapshot, AgentIdStrategy, Annotator) -> AgentView`，payload = 全量块拼接 + ID 标注（Docs/Design/06-view.md）
- 现状：View 是**全量、无损**的。ReferenceMap 必须双射且**覆盖全部 blocks**。
- 已有研究框架：操作面（rewrite / find_replace / patch / swe_edit）作为独立变量（Docs/drafts/2026-09-03-operation-surface-brief.md）
- 拟扩展变量：**视图粒度/省略策略**（analogy：只留函数签名、省略函数体）

## 阶段
- [x] P0 检索：coding agent 的 repo map / 代码骨架 / 上下文压缩
- [x] P0 检索：长上下文 LLM 的 context pruning / compression / progressive disclosure
- [x] P1 检索：文档编辑 agent / OCR 后矫正的上下文单位
- [x] P1 检索：ACI（Agent-Computer Interface）与 view 设计的受控实验
- [x] P2 归纳 gap（5 类）+ 出 Research Question Card

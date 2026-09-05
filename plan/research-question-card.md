# Research Question Card — 视图粒度作为独立变量

日期：2026-09-04 ｜ 状态：未通过 proposal 证据门（证据为摘要级）
关联：`Docs/drafts/2026-09-04-view-granularity-litreview.md`、`Docs/drafts/2026-09-03-operation-surface-brief.md`

## RQ（主）
在 fidelity-constrained 的文本修复任务上，**视图的有损投影强度**（全量 → 摘要 → 省略但可寻址）
是否与 **操作面** 存在交互效应，且最优投影强度是否随输入噪声水平**单调下降**？

## 假设
- **H1（结构性上界）**：不进入 View 的块无法被编辑指令触及，因此 spurious edit（cMER 中的 I 与非必要 S）随省略强度单调下降。
- **H2（噪声交互）**：在低噪声（dta19-l0）上省略净收益为正；随噪声升高（l1→l2）转为净损失。交叉点存在。
- **H3（寻址 vs 信息）**：「省略但保留 id」优于「省略且不保留 id」——即部分能力损失来自寻址损失而非信息损失。

## 当前证据
- 领域痛点被官方量化：dta19-l0 上冠军系统 cMER 仅 0.0040 → 0.0029（HIPE 2607.08143 Table 7）。
- over-correction 被官方三次列为 open problem（§1、§6、§7）。
- 骨架化上下文在 coding agent 中普遍存在但从未作为变量（aider / SWE-Fixer / LocAgent）。
- 唯一受控的披露实验只覆盖 QA（2607.17598）。

## 缺失证据
- 本仓库尚无任何有损 View 的实现或运行数据（`Projection` 未定义）。
- H3 所需的「省略且不保留 id」臂在架构上目前不可表达（ReferenceMap 强制覆盖全部 blocks）。
- 上述 11 条文献均为摘要级，未全文核验。

## 支持标准
在 l0 上，某一非零省略强度使 cMER 显著低于全量视图（同模型、同操作面、同 annotator、同 id 策略），
且 I 分量下降幅度大于 D 分量上升幅度。

## 证伪标准
在全部三个噪声档上，任意非零省略强度的 cMER 都不优于全量视图；或收益不随噪声档变号（H2 的交互不存在）。

## 最小下一步
1. 核验第 6、7 条来源（LocAgent 粒度档、SWE-Fixer skeleton 定义）——决定「无人做过」这句能不能写。
2. 用 `--replay` 在**已有磁带**上做零 API 成本的 S/D/I 分量分解，确认 l0/l1/l2 上 I 与 D 的比例确实随噪声变号。
   这一步不需要任何新代码路径，只动报告端。
3. 只有 2 的结果支持 H2 的方向，才动 `Projection` 的实现。

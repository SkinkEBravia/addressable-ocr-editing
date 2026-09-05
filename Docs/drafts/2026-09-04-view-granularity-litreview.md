---
title: 视图粒度（View Granularity）作为上下文管理变量
subtitle: 文献调研与 Gap 分析 —— 为 06-view.md 的省略式视图扩展定位
date: 2026-09-04
status: draft / 证据等级见文末
evidence_level: 摘要级（abstract-level），未做全文核验
related: 2026-09-03-operation-surface-brief.md
tags: [ContextEngineering, ACI, PostOCR, View, LLMAgent]
---

# 视图粒度作为上下文管理变量：文献调研与 Gap 分析

> [!abstract] TL;DR
> 1. 「省略函数体、只留签名」这个动作在 coding agent 工程里**早已是标配**（aider repo map、SWE-Fixer skeleton、LocAgent fold/preview/full），但它一直被当作**token 预算手段**，不是被控变量。
> 2. 唯一把「渐进式披露」做成受控实验的工作（arXiv 2607.17598）**只测 QA/检索，不测编辑**，且结论偏消极：一层披露有用，两层从不有用、有时更差。
> 3. 上下文压缩文献（ACON、TRACE、Squeez）压的是**轨迹**（历史 + 工具输出），不是**被编辑的工件本身**。工件的有损视图是空白区。
> 4. 本仓库 IR 提供一个别人没有的条件：**视图有损、工件无损、被省略的块仍可寻址**（`BlockKey` 保留在 `ReferenceMap` 中）。这不是 code skeleton 的性质——skeleton 里被折叠的函数体是不可操作的。
> 5. 最有价值的 gap 不是「省略能省 token」（这条正在被 reasoning 模型证伪），而是**「省略能不能作为 over-correction 的结构性上界」**——没进视图的文本，模型物理上改不到。HIPE 官方把 over-correction 列为 open problem，dta19-l0/l1/l2 是现成的免费噪声阶梯。

---

## 0. 调研问题

本仓库 View 层现状（`Docs/Design/06-view.md`）：

```python
present(snapshot, strategy, annotator) -> AgentView
# payload = 按序对每个块应用 annotator(strategy(block, i), block.content) 并拼接
# ReferenceMap 双射且覆盖全部 blocks
```

即 **View 目前是全量、无损的**：一个块要么完整出现，要么根本不存在。
拟扩展的方向：允许 View 对块做**有损投影**（省略 / 摘要 / 占位 / 只留元信息），同时保留寻址能力。

调研问题：这件事在文献里被做到什么程度？还剩哪些空地？

---

## 1. 现有工作的五个簇

### 簇 A —— Coding agent 的骨架化上下文（工程成熟，科学空白）

| 系统 | 做法 |
|---|---|
| aider repo map | 全仓库的类/函数**签名与类型**，只保留被引用最多的 identifier |
| SWE-Fixer | 文件"skeleton"：module docstring + class header + method signature + 函数体**首尾各 5 行** |
| 某些 scaffold | 超 128K 时按排名丢文件，并用 libcst 把函数体**压成签名** |
| LocAgent | 工具输出分 `fold` / `preview` / `full` 三档粒度 |

这一簇就是用户设想的原型。关键判断：

> [!important] 它们从来不是变量
> 粒度档位是**实现细节**，由工程直觉设定。检索到的唯一定量说法是一句附带观察——"用完整文件内容不仅更贵，而且**减少**了定位到 ground truth 的问题，可能因为 LLM 处理长上下文不好"——即完整内容有时**优于** skeleton。这条方向相反的观察没有被作为受控实验展开。

`Inside the Scaffold`（arXiv 2604.03515）把 13 个开源 coding agent scaffold 拆成 12 个维度、3 层（control architecture / tool-environment interface / resource management），把 context strategy 明确列为 scaffold 的一等成分——**分类学已经建立，因果实验还没有**。

### 簇 B —— 长程 agent 的上下文压缩（压的是轨迹，不是工件）

| 工作 | 对象 | 关键结论 |
|---|---|---|
| ACON (ICML 2026, arXiv 2510.00615) | 环境观测 + 交互历史 | peak token 降 26–54%，性能基本保持；小模型最多 +46% |
| TRACE / Toward Reliable Context Compression (arXiv 2608.06503) | 交互历史 | 压缩导致**状态失定位**、**回退式探索**、**执行不稳定**；FIFO 截断在中等预算下有时**打平甚至优于**摘要 |
| Squeez (arXiv 2604.04979) | 工具输出 | 任务条件化剪枝 |
| Multi-Rubric Latent Reasoning (arXiv 2605.15315) | coding agent 上下文 | 多准则剪枝 |

> [!note] 边界很清楚
> 这一簇全部作用于**对话轨迹**（history / observation / tool output）。**被编辑的工件本身**（文件、文档）的有损表示不在其射程内。而在 OCR 后矫正里，工件就是全部——轨迹通常只有一两轮。

### 簇 C —— 渐进式披露（唯一的受控实验，但不做编辑）

`Is Progressive Disclosure All You Need for Long-Context Agents?`（arXiv 2607.17598）：

- 设计：3 个 harness × 3 个模型族 × {raw navigation, 多种 Agent Skills 披露设计, 经典 hybrid retriever}，InfiniteBench。
- 结论：**语料规模超过 agent 自主导航能力时，披露带来的是上下文效率，不是智能优势**；一层披露随语料增大优于 raw navigation；**第二层路由从不帮忙，有时直接破坏准确率**。
- **范围：只有检索与问答，不涉及编辑或写作。**

这是目前最接近"把视图粒度当变量"的工作，也直接说明了空地在哪：**任务类型是 QA，不是 fidelity-constrained editing。**

### 簇 D —— 位置与干扰效应（机制解释，测的仍是检索）

Lost-in-the-middle：相关信息落在中部时准确率下降 30%+，U 形；RoPE 长程衰减 + softmax 归一化是机制解释。语义相近但无关的 distractor 造成的退化超过长度本身能解释的部分。

> [!tip] 对本课题的意义
> 这一簇给出**为什么省略式视图可能提高定位精度**的机制理由（削掉 distractor、把可疑区推向首尾）。但它测的是 retrieval accuracy，**没有人把它翻译成 edit precision**。

### 簇 E —— 任务域：post-OCR 与文档编辑 agent

**HIPE-OCRepair-2026（arXiv 2607.08143）**：

- 上下文被官方定义**锁死**在 transcription unit = "a paragraph or article"。
- over-correction 是官方三次点名的 open problem：`"Overcorrection on low-noise inputs emerges as a recurring challenge"`（§1）、`"developing methods to control overcorrection and hallucination"`（§7 future work）。
- 相关工作已证明**跨段上下文有用**：切成不重叠段落导致每段开头没有左上下文，补上下文能显著改善段边界处的后矫正效果（CLOCR-C 一系）。

**post-OCR 的 detect-then-correct 传统**（两步法、confidence-aware detection）：

> "Splitting the task into error detection and correction increases the proportion of OCR errors which are fed into the corrector model and decreases the amount of erroneously changed correct tokens since tokens classified as correct are not passed through the error corrector model."

> [!important] 这是省略式视图最近的表亲
> 逻辑完全一致——**没送进纠错器的 token 不会被改坏**。但它是**流水线过滤器**（把干净 token 从输入里删掉，纠错器看不到任何上下文），不是**视图投影**（保留全局上下文与寻址、只省略呈现）。两者的差别正是本课题的空间。

**文档编辑 agent**：LEDGER（arXiv 2606.28379）明确写道，长文档编辑中"朴素地把全文当上下文既低效又适得其反"，而基于话题相似度的检索"经常漏掉对一致性至关重要的结构依赖"。方案是 dependency-aware graph retrieval。
注意其目标函数是**指令遵循**（"revise the tone of Section 4"），不是**保真修复**。

---

## 2. Gap 分析

> 分类沿用 5 类 gap（文献 / 方法 / 应用 / 交叉 / 时序）。按可执行性排序。

### G1（方法 gap，最强）视图与操作面在所有现有系统里是混淆的

现有三条路线，视图和操作面**捆绑出现**：

| 操作面 | 隐含的视图 |
|---|---|
| rewrite | 全量、无标注 |
| find_replace / grep | 检索窗口，全局不可见 |
| patch | 全量、带块标注 |

没有人做过 **View × Operation surface 的交叉设计**。
`More Is Not Always Better: Cross-Component Interference in LLM Agent Scaffolding`（arXiv 2605.05716）给出方法学先例：5 个 scaffold 组件的全因子（32 子集 × 2 benchmark × 3 模型族 × 5 规模 ≈ 32000 次评测），并明确指出**此前工作从未用全因子设计，因而看不到高阶交互**。

本仓库的架构恰好允许解耦：`AgentIdStrategy` / `Annotator` / patch 方言在 06-view.md 与 07-agent-api.md 里已经是独立可替换点。加一个 `Projection`（决定哪些块以什么形态出现）就得到第三个正交轴。

**空地陈述**：视图粒度作为独立变量、与操作面交叉、在编辑任务上测量——无人做过。

### G2（文献 gap）「视图有损、工件无损、省略仍可寻址」是未探索的机制

压缩文献的默认假设是：信息丢了就是丢了，风险在于任务状态损坏（TRACE 观察到的状态失定位正是这个）。

本仓库的 IR 给出一个不同的机制：

- `DocumentSnapshot` 是权威数据，View 是派生物（03-ir-data.md 明写"View、索引等一切下游均为派生物"）；
- `ReferenceMap` 可以**继续覆盖全部 blocks**，即使 payload 只渲染其中一部分；
- 于是 agent 可以对**它看不见的块**发出操作（`keep(b17)`、`expand(b17)`、甚至 `delete(b17)`）。

code skeleton 没有这个性质：被折叠的函数体不可寻址、不可操作。

**空地陈述**：「对未呈现内容的可寻址操作」在文献中没有对应物，因而"省略造成的能力损失"到底是**信息损失**还是**寻址损失**，从未被分离过。这是一个可以设计干净实验的机制问题（省略但保留 id vs 省略且不保留 id）。

### G3（应用 gap，最可发表）省略作为 over-correction 的结构性上界

领域公认的痛点被官方量化：dta19-l0（低噪声）上冠军系统只把 cMER 从 0.0040 降到 0.0029，而 l2 上降 85%。

现有控制手段都是**行为性**的（prompt 约束、fine-tune、constrained decoding 的语法约束）。省略式视图给出的是**结构性**的：

> 不进入视图的文本，模型无法生成对它的编辑指令，因此 spurious edit 的上界由投影策略决定，而不是由模型的克制程度决定。

这一条在 constrained decoding 文献里没有对应（那里约束的是输出**格式**，不是输出可触及的**区域**）；在 detect-then-correct 里逻辑相同但代价是丢掉上下文。

**可执行实验**：`dta19-l0/l1/l2` 共享同一批 11 篇源文档、同样页码抽样，只有退化程度不同 —— 免费的噪声阶梯。假设：**最优省略强度随噪声水平单调下降**（越干净越该多省）。这是一个明确的、可证伪的交互效应预测。

### G4（交叉 gap）保真型编辑 vs 指令遵循型编辑，上下文管理文献只为后者写

LEDGER / DocEdit / Canvas 一类都在优化"按指令改对"。post-OCR 优化的是"**别乱改**"——cMER 把插入放进分母正是为了惩罚过度生成。

上下文管理的所有既有结论（压缩省钱、披露有用、骨架够用）都是在**指令遵循 + 任务成功率**这个目标函数下得到的。在保真目标函数下它们是否成立，没有人验证。有理由预期结论会翻转：**丢信息在"改对"任务里是纯损失，在"别乱改"任务里可能是净收益。**

### G5（时序 gap）reasoning 模型正在废掉「省 token」这条论证

- 渐进式披露论文：`"no intelligence advantage when capable agents already retrieve passages effectively"`；
- ACON 的收益被表述为 memory / peak token，而非能力；
- 本仓库自己的初步结果：token efficiency 假设在 reasoning 模型上**被否证**（见 09-03 brief）。

**空地陈述**：省略式视图在 2026 年若还有价值，论证必须从**成本**转到**精度/保真**。这个重构本身就是一个可发表的立场，且正是领域还没往里看的方向。

### 附加：测量 gap

cMER 是标量，把两类错误混在一起：

- 省略视图造成的**漏改**（false negative → D/S 残留）
- 全量视图造成的**乱改**（false positive → I 与不必要的 S）

`report.json` 已经能拿到对齐后的 H/S/D/I 分量。**按投影策略分解 S/D/I** 是一个几乎零成本、但文献里没人做的测量动作，且直接支撑 G3 的假设。

---

## 3. 与本仓库设计的接口影响（供 06-view.md 修订参考）

当前契约的两条会被有损视图触碰：

```text
payload = 按序对每个块应用 annotator(strategy(block, i), block.content) 并拼接
ReferenceMap 双射且覆盖快照的全部 blocks
```

建议的最小改动（尚未实施，仅为讨论）：

- 新增第三个正交可替换点 `Projection: (Block, index) -> RenderedForm`，`RenderedForm ∈ {Full, Elided(placeholder), Digest(summary/stats), Omitted}`；
- **保持 `ReferenceMap` 覆盖全部 blocks 不变**——这是 G2 的实验前提，不能为了省事让被省略的块掉出映射；
- `render_spec` 记录 projection 名，使 View 可比较、可复现（沿用"同一 (snapshot, strategy, annotator) 结果确定"的验收条款，扩成四元组）；
- 变量隔离纪律沿用 06-view.md 已有原则：**比较 projection 时，id 策略与标注形式必须固定**。

---

## 4. 证据等级与限制

> [!warning] 诚实的状态
> - 本文全部依据为**检索摘要级证据**，未做全文核验。arXiv 编号（2604.\*/2605.\*/2606.\*/2607.\*/2608.\*）**在引用前必须逐条核对**标题、作者、年份与实际结论。
> - "LocAgent 有 fold/preview/full 三档"来自检索摘要，两次尝试取全文均失败，**未确认**。
> - "完整文件内容优于 skeleton"的那句观察，来源归属尚未确定（可能来自 Agentless 或 SWE-Fixer 的讨论段），**未确认**。
> - G1 的"无人做过"是**基于当前检索的否定性判断**，否定性结论最容易出错；正式写作前需要至少一轮 Google Scholar + ACL Anthology 的定向复查。

### 设计风险（与文献无关，属方案本身）

代码有天然的省略边界（函数体）；散文没有。**投影策略必须自己充当一个错误检测器**，于是整个系统的召回上界被这个检测器锁死——这恰是两步法 post-OCR 的已知弱点。若不解决，G3 的"结构性上界"会退化成"结构性天花板"。
可能的缓解：保留 `expand(bN)` 让 agent 自己撤销省略（这也正好把 G2 变成可测的）。

---

## 5. 待核验来源

| # | 标题 | 用途 | 状态 |
|---|---|---|---|
| 1 | Is Progressive Disclosure All You Need for Long-Context Agents? (2607.17598) | 唯一受控实验；范围限 QA | 摘要已读 |
| 2 | Toward Reliable Context Compression for Long-Horizon Agents (2608.06503) | 压缩的失败模式 | 摘要+结论已读 |
| 3 | ACON (2510.00615, ICML 2026) | 压缩收益量级 | 摘要已读 |
| 4 | More Is Not Always Better: Cross-Component Interference (2605.05716) | 全因子设计方法学先例 | 摘要已读 |
| 5 | Inside the Scaffold (2604.03515) | scaffold 分类学 | 摘要已读 |
| 6 | LocAgent (ACL 2025 long 426 / 2503.09089) | fold/preview/full 粒度 | **全文取用失败** |
| 7 | SWE-Fixer (Findings ACL 2025) | skeleton 定义 | 摘要已读 |
| 8 | LEDGER (2606.28379) | 长文档编辑的上下文检索 | 摘要已读 |
| 9 | HIPE-OCRepair-2026 (2607.08143) | 任务定义 + over-correction | 已有全文（09-03 brief 已引） |
| 10 | CLOCR-C (2408.17428) | 跨段上下文的作用 | 摘要已读 |
| 11 | aider repo map (docs) | 工程实践基线 | 文档已读 |
| 12 | A Two-Step Approach for Automatic OCR Post-Correction (LaTeCH-CLfL 2020) | detect-then-correct | 摘要已读 |

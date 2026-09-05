---
title: 文献索引（arXiv 号 / URL / 证据等级）
date: 2026-09-04
status: working index —— 随调研更新
related:
  - "[[2026-09-03-operation-surface-brief]]"
  - "[[2026-09-04-view-granularity-litreview]]"
tags:
  - References
  - PostOCR
  - ACI
  - ContextEngineering
---

# 文献索引

> [!abstract] 用途
> 把 `2026-09-03-operation-surface-brief.md`（操作面）与 `2026-09-04-view-granularity-litreview.md`（视图粒度）两份调研中出现的全部来源收在一处，只记**标识符、链接、用途、证据等级**。不写论述 —— 论述在那两份文档里。

## 证据等级图例

| 记号 | 含义 |
|---|---|
| ✅✅ | **全文核验** —— 抓到 HTML/正文并提取了逐字引文，可直接引用 |
| ✅ | **摘要核验** —— 读过 abstract 或 landing page，结论方向可信，细节需查 |
| ⚠️ | **检索摘要** —— 只有搜索引擎返回的片段，**论文本体未打开**，标题/作者/年份/结论均需核对 |
| ❌ | **取用失败** —— 尝试过但拿不到全文 |

> [!warning] 使用前必读
> 标 ⚠️ 的条目**不得直接进论文引用列表**。这些 arXiv 编号来自检索结果列表，我没有打开过论文本体 —— 编号、标题、结论三者的对应关系都可能错。正式写作前必须逐条打开核对。
>
> 另外：`2026-09-04-view-granularity-litreview.md` 整篇的自评就是「摘要级证据，未做全文核验」，其 G1 的「无人做过」是**否定性判断** —— 否定性结论最容易出错，需要一轮 Google Scholar + ACL Anthology 定向复查。

---

## A. 任务域：OCR 后矫正 / HIPE

| arXiv / ID | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2607.08143](https://arxiv.org/abs/2607.08143) | ICDAR 2026 HIPE-OCRepair Competition on LLM-Assisted OCR Post-Correction | **本项目数据集与指标的权威来源**；cMER 定义；官方 Table 7；over-correction 被三次点名为 open problem | ✅✅ |
| [2502.01205](https://arxiv.org/abs/2502.01205) | OCR Error Post-Correction with LLMs in Historical Documents: No Free Lunches | LLM 后矫正的能力边界（英语可用、芬兰语不可用） | ✅ |
| [2504.00414](https://arxiv.org/abs/2504.00414) | Multimodal LLMs for OCR, OCR Post-Correction, and NER in Historical Documents | 指出既有后矫正工作 "exclusively text-based"；转向多模态 | ⚠️ |
| [2602.21053](https://arxiv.org/abs/2602.21053) | OCR-Agent: Agentic OCR with Capability and Memory Reflection | agentic OCR，但是 VLM 自反思，**不是编辑面** | ⚠️ |
| [2408.17428](https://arxiv.org/abs/2408.17428) | CLOCR-C | 跨段上下文对后矫正有用（段边界处改善明显） | ⚠️ |
| [2510.06743](https://arxiv.org/abs/2510.06743) | Evaluating LLMs for Historical Document OCR | 12 个多模态 LLM 评测；"over-historicization" 现象 | ⚠️ |
| [2412.15248](https://arxiv.org/abs/2412.15248) | RoundTripOCR（低资源天城文后矫正数据生成） | 数据增强路线，与本课题关系弱 | ⚠️ |
| [2102.00583](https://arxiv.org/abs/2102.00583) | Neural OCR Post-Hoc Correction of Historical Corpora | 神经后矫正的早期代表 | ⚠️ |
| [aclanthology 2020.latechclfl-1.6](https://aclanthology.org/volumes/2020.latechclfl-1/) | A Two-Step Approach for Automatic OCR Post-Correction（LaTeCH-CLfL 2020） | **detect-then-correct 传统 —— 省略式视图最近的表亲**；"未送进纠错器的 token 不会被改坏" | ⚠️ 卷号待定位 |
| [rs-6823036](https://www.researchsquare.com/article/rs-6823036/v1) | Post-OCR Correction Using LLMs with Constrained Decoding | **动机最接近的竞争工作**：decoding 层约束 vs 本课题的操作面层约束 | ❌ HTTP 403 |

**官方资源（非论文）**

| 资源 | URL |
|---|---|
| HIPE-OCRepair 官方 scorer | https://github.com/hipe-eval/HIPE-OCRepair-scorer |
| HIPE-OCRepair-2026 数据与参赛指南 | https://github.com/hipe-eval/HIPE-OCRepair-2026-data |

---

## B. 操作面 / ACI / harness（本课题最重要的对话对象）

| arXiv | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2405.15793](https://arxiv.org/abs/2405.15793) | SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering（NeurIPS 2024） | **ACI 概念奠基**；四条设计原则；edit+lint / file-viewer 窗口的 ablation（100 行 18.0% vs 全文件 12.7%） | ✅✅ ar5iv |
| [2607.10569](https://arxiv.org/abs/2607.10569) | When Does Restricting a Coding Agent to `execute_code` Help? A Regime-Stratified Study | **最重要的对撞对象**："Pass rates differ by less than three percentage points across every cell while costs swing 20–40%"；且**未拆 reasoning token** | ✅✅ |
| [2604.03515](https://arxiv.org/abs/2604.03515) | Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures | 13 个 scaffold × 12 维度 × 3 层；context strategy 被列为一等成分（分类学已立，因果实验未做） | ✅ |
| [2607.22585](https://arxiv.org/abs/2607.22585) | The Scaffold Effect in Coding Agents: Harness Choice as a Hidden Variable | "harness 是隐藏变量"的直接论证 | ⚠️ |
| [2607.04528](https://arxiv.org/abs/2607.04528) | Measuring Harness-Induced Belief Divergence in Multi-Step LLM Agents | harness 对 agent 内部状态的影响 | ⚠️ |
| [2606.12882](https://arxiv.org/abs/2606.12882) | HarnessBridge: Learnable Bidirectional Controller for LLM Agent Harness | harness 可学习化 | ⚠️ |
| [2608.25593](https://arxiv.org/abs/2608.25593) | Scaling Harness Intelligence via Just-in-Time Harness Evolution | harness 自演化 | ⚠️ |
| [2604.05407](https://arxiv.org/abs/2604.05407) | CODESTRUCT: Code Agents over Structured Action Spaces | 结构化动作空间 —— 名字上最接近本课题，**优先核** | ⚠️ |

---

## C. 编辑格式 / diff 表示

| arXiv / ID | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2604.27296](https://arxiv.org/abs/2604.27296) | To Diff or Not to Diff? Structure-Aware and Adaptive Output Formats for Efficient LLM-based Code Editing | 三种 diff 风格对比；search/replace 的分隔符冲突风险（本项目 `fn` 方言结构上免疫）；"reduces cost by over 30%"；**未拆 reasoning token** | ✅✅ |
| [2604.26102](https://arxiv.org/abs/2604.26102) | SWE-Edit: Rethinking Code Editing for Efficient SWE-Agent | find-replace 与 whole-file-rewrite 自适应选择；resolve +2.1pp / cost −17.9% | ✅ |
| [2604.18170](https://arxiv.org/abs/2604.18170) | Copy-as-Decode: Grammar-Constrained Parallel Prefill for LLM Editing | **解码侧**解决"未变文本要重新生成"；round-trip exact-match 完美 | ⚠️ |
| [2604.19201](https://arxiv.org/abs/2604.19201) | Cascaded Code Editing: Large-Small Model Collaboration | 疑为 "Context Tax" 概念出处之一，**待核** | ⚠️ |
| [2510.12487](https://arxiv.org/abs/2510.12487) | Diff-XYZ: A Benchmark for Evaluating Diff Understanding | diff 理解能力的基准 | ⚠️ |
| [aider docs](https://aider.chat/docs/more/edit-formats.html) | Aider — Edit formats | **"编辑格式省 token"这个信念最赤裸的出处**："it can be slow and costly because the LLM has to return the _entire file_" | ✅✅ |
| [aider notes](https://aider.chat/docs/leaderboards/notes.html) | Aider — Benchmark notes | "Models which can use one of the diff formats are much more efficient, using far fewer tokens" | ✅✅ |
| [Anthropic docs](https://docs.claude.com/en/docs/build-with-claude/tool-use/text-editor-tool) | Text editor tool（`str_replace`） | 官方只描述行为，**未给出 token 效率论述** —— 别引成"官方也这么说" | ✅ |

---

## D. 文档保真 / 轮数效率

| arXiv | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2604.15597](https://arxiv.org/abs/2604.15597) | LLMs Corrupt Your Documents When You Delegate（DELEGATE-52） | **本课题动机的独立验证**：前沿模型 20 轮腐蚀 ~25%；**给工具反而更差（多退化 6%）**；sparse critical failures 解释 80% 腐蚀；size × 轮数乘性复合 | ✅✅ |
| [2606.30775](https://arxiv.org/abs/2606.30775) | A Single Rewrite Suffices: Empirical Lessons from Production Skill Description Optimization | **"少轮数"主张最接近的邻居**：单次重写 ≈ 最多 10 轮迭代（差 0.2%）。但域是 tool description 优化、**无保真约束** | ❌ PDF 不可抽取 |
| [2606.28379](https://arxiv.org/abs/2606.28379) | LEDGER（长文档编辑的 dependency-aware graph retrieval） | 长文档编辑："朴素地把全文当上下文既低效又适得其反"；但目标是**指令遵循**不是保真修复 | ⚠️ |
| [2309.15337](https://arxiv.org/abs/2309.15337) | Beyond the Chat: Executable and Verifiable Text-Editing with LLMs | 显式可执行编辑列表 + 人工逐条接受/拒绝。最接近的**交互式**先行工作，目标是人类可验证性 | ⚠️ |

---

## E. 上下文压缩 / 视图粒度（09-04 调研）

| arXiv / ID | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2607.17598](https://arxiv.org/abs/2607.17598) | Is Progressive Disclosure All You Need for Long-Context Agents? | **唯一把渐进式披露做成受控实验的工作**；结论偏消极（一层有用、两层从不有用有时更差）；**范围只有 QA/检索，不含编辑** | ✅ |
| [2510.00615](https://arxiv.org/abs/2510.00615) | ACON（ICML 2026） | 上下文压缩收益量级：peak token 降 26–54% | ✅ |
| [2608.06503](https://arxiv.org/abs/2608.06503) | Toward Reliable Context Compression for Long-Horizon Agents（TRACE） | 压缩的失败模式：状态失定位、回退式探索；FIFO 截断有时打平摘要 | ✅ |
| [2604.04979](https://arxiv.org/abs/2604.04979) | Squeez（工具输出的任务条件化剪枝） | 压缩对象是**工具输出**，不是被编辑的工件 | ⚠️ |
| [2605.15315](https://arxiv.org/abs/2605.15315) | Multi-Rubric Latent Reasoning | coding agent 上下文的多准则剪枝 | ⚠️ |
| [2605.05716](https://arxiv.org/abs/2605.05716) | More Is Not Always Better: Cross-Component Interference | **全因子设计的方法学先例** —— 本课题实验设计可参照 | ⚠️ |
| [2605.04050](https://arxiv.org/abs/2605.04050) | LCM: Lossless Context Management | 大文件外置 + opaque ID 引用。寻址相邻，但作用于上下文管理不是编辑 | ⚠️ |
| [2602.05892](https://arxiv.org/abs/2602.05892) | ContextBench: A Benchmark for Context Retrieval in Coding Agents | 检索能力的基准 —— 本课题想**消除**的那一步 | ⚠️ |
| [2503.09089](https://arxiv.org/abs/2503.09089) | LocAgent（ACL 2025 long 426） | `fold` / `preview` / `full` 三档粒度 —— 视图粒度的现成原型 | ❌ 两次全文取用失败 |
| ACL Findings 2025 | SWE-Fixer | file "skeleton" 的定义（docstring + class header + signature + 函数体首尾各 5 行） | ⚠️ 需定位 anthology 号 |
| [aider repo map](https://aider.chat/docs/repomap.html) | Aider — Repository map | 骨架化上下文的工程基线 | ✅ |

---

## F. reasoning token 成本

| arXiv | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [2605.07686](https://arxiv.org/abs/2605.07686) | The Coupling Tax: How Shared Token Budgets Undermine Visible Chain-of-Thought Under Fixed Output Limits | reasoning 与答案共享输出预算的结构性问题 —— 与本项目"思考淹没输出"同频 | ⚠️ |
| [2608.27506](https://arxiv.org/abs/2608.27506) | Thinking Costs Tokens: When More Structure is Worth the Price | 结构化推理的性价比阈值（~1500 输出 token 以下结构反而有害） | ⚠️ |

---

## G. 编辑表示（NLP 传统，Related Work 需切干净）

| arXiv / ID | 标题（简） | 用途 | 证据 |
|---|---|---|---|
| [aclanthology 2020.bea-1.16](https://aclanthology.org/2020.bea-1.16/) | GECToR – Grammatical Error Correction: Tag, Not Rewrite（BEA 2020） | seq2edit 路线代表。**区别：那是模型架构，不是 agent 工具契约** | ✅ |
| [2404.14914](https://arxiv.org/abs/2404.14914) | Pillars of Grammatical Error Correction（LLM 时代的 GEC 综述） | seq2seq vs seq2edit 两条路线的综述性对比 | ⚠️ |
| [2310.10480](https://arxiv.org/abs/2310.10480) | G-SPEED: General SParse Efficient Editing MoDel | 高效编辑模型 | ⚠️ |

---

## H. 边缘 / 未评估（检索时出现过，相关性待判断）

> [!note]
> 这一组我**只在检索结果里见过标题**，没有判断过与本课题的关系。留在这里避免下次重复检索，不代表推荐引用。

| arXiv | 标题（简） |
|---|---|
| [2603.05344](https://arxiv.org/abs/2603.05344) | Building Effective AI Coding Agents for the Terminal: Scaffolding, Harness, Context Engineering |
| [2606.17454](https://arxiv.org/abs/2606.17454) | Dissecting model behavior through agent trajectories |
| [2607.02606](https://arxiv.org/abs/2607.02606) | ChainSWE: Benchmarking Coding Agents on Multi-Bug Software Maintenance |
| [2606.20683](https://arxiv.org/abs/2606.20683) | From Question Answering to Task Completion: A Survey on Agent System |
| [2409.07732](https://arxiv.org/abs/2409.07732) | LLMs are Pattern Matchers: Editing Semi-Structured and Structured Documents with ChatGPT |
| [2404.07108](https://arxiv.org/abs/2404.07108) | Revision Distance as a Metric for Text Evaluation |
| [2305.15685](https://arxiv.org/abs/2305.15685) | RewriteLM: An Instruction-Tuned LLM for Text Rewriting（AAAI） |
| [2510.13859](https://arxiv.org/abs/2510.13859) | Benchmarking Correctness and Security in Multi-Turn Code Generation |

---

## 批量导入用（Zotero「从标识符添加」可整段粘贴）

> Zotero → 文件 → 从标识符添加（Add Item by Identifier）→ 点右下角展开成多行输入框 → 整段粘贴。

### A+B+C 组（操作面主线，18 条）

```text
2607.08143
2502.01205
2504.00414
2602.21053
2408.17428
2510.06743
2405.15793
2607.10569
2604.03515
2607.22585
2607.04528
2604.05407
2604.27296
2604.26102
2604.18170
2604.19201
2510.12487
2404.14914
```

### D+E+F 组（保真 / 视图粒度 / token 成本，15 条）

```text
2604.15597
2606.30775
2606.28379
2309.15337
2607.17598
2510.00615
2608.06503
2604.04979
2605.15315
2605.05716
2605.04050
2602.05892
2503.09089
2605.07686
2608.27506
```

### 低优先（边缘组，8 条）

```text
2603.05344
2606.17454
2607.02606
2606.20683
2409.07732
2404.07108
2305.15685
2510.13859
```

---

## 核验待办（按优先级）

| P | 动作 | 为什么 |
|---|---|---|
| P0 | 打开 [2607.10569](https://arxiv.org/abs/2607.10569) §5.1 成本表与实验设置，确认**所用模型是否开 thinking** | 决定"编辑格式省 token 在 reasoning 模型上失效"这个卖点是否原创。若他们用的是非 reasoning 模型，本课题的边界论证非常干净 |
| P0 | 打开 [2604.27296](https://arxiv.org/abs/2604.27296) Table 3 与实验设置，同上 | 同上 |
| P0 | 定位 "Context Tax" 的确切出处（疑 [2604.19201](https://arxiv.org/abs/2604.19201) 或 [wuu73 博客](https://wuu73.org/aiguide/infoblogs/coding_file_edits/methods.html)） | 若已是正经论文里的概念，Related Work 必须引并说清区别（它是**可见上下文**的消歧开销，本课题是**思考阶段**的开销，方向相反） |
| P1 | 下载 [rs-6823036](https://www.researchsquare.com/article/rs-6823036/v1) PDF | 动机最接近的竞争工作，作者/年份/数字全部未核 |
| P1 | 打开 [2607.08143](https://arxiv.org/abs/2607.08143) §5.2 四支队伍方法的**完整段落** | 要断言"没人动过操作面"必须逐段读完，现有引文只到摘要级 |
| P1 | 打开 [2604.05407](https://arxiv.org/abs/2604.05407) CODESTRUCT | 标题上最接近"结构化动作空间"，是最可能撞车的一篇 |
| P1 | 打开 [2607.17598](https://arxiv.org/abs/2607.17598) 全文 | 09-04 调研的核心支点，目前只有摘要 |
| P2 | 定位 LocAgent（[2503.09089](https://arxiv.org/abs/2503.09089) / ACL 2025）与 SWE-Fixer 的 anthology 号 | fold/preview/full 三档与 skeleton 定义都是二手转述 |
| P2 | Google Scholar + ACL Anthology 定向复查，覆盖 ICDAR / DAS / TPDL / JCDL proceedings | 两份调研的"无人做过"都是否定性判断，且只做了关键词检索 |

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-04 | 建立索引；合并 09-03 操作面调研（约 28 条）与 09-04 视图粒度调研（11 条），去重后 A–H 共 8 组 |

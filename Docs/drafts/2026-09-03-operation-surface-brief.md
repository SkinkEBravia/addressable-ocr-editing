---
title: 操作面（Operation Surface）作为 LLM 文本修复的独立变量
subtitle: HIPE-OCRepair-2026 上的初步证据与研究计划
date: 2026-09-03
status: draft / 讨论用
audience: advisor
tags:
  - OCR
  - PostCorrection
  - LLMAgent
  - ACI
  - HIPE
---

# 操作面作为 LLM 文本修复的独立变量

> [!abstract] TL;DR
> 1. **问题**：LLM 做 OCR 后矫正时，"暴露给模型什么编辑操作"（全文重写 / 检索后局部替换 / 显式标注块 + 结构化编辑）从未被当作受控变量研究过。竞赛的四支队伍差异全在**模型适配**维度（zero-shot / fine-tune / continued pretrain），没有一支动**操作面**维度。
> 2. **假设**：人类修复文本的方式是"先看完整上下文，再聚焦局部操作"。若在 context 中对分块**显式标注**并给 LLM 一套按块操作的工具，模型可以用 attention 自行聚焦，从而优于（a）全文重写和（b）间接聚焦（grep 读片段 + find_replace 改片段）；且该优势随上下文增大而增大。
> 3. **初步证据（n=1 文档，单模型）**：出现了一个**交叉交互效应**。孤立小块上两种操作面打平；一旦对话累积历史或输入变长，结构化编辑改善、全文重写退化。这与 coding-agent 社区已发表的"操作面只影响成本、不影响能力"相反。
> 4. **诚实的状态**：三条假设中，一条初步支持、一条**完全未验证**（find_replace 臂尚未运行）、一条**被否证**（token efficiency 在 reasoning 模型上不成立——这本身是可发表的负结果）。当前证据不足以下结论，但足以决定下一步该烧哪些 token。

---

## 1. 背景：HIPE-OCRepair-2026 这个任务

### 1.1 任务是什么

HIPE-OCRepair-2026 是 ICDAR 2026 的一个竞赛[^hipe]，主题是**用 LLM 修复历史文献的 OCR 错误**，不给原始图像，只给 OCR 文本。语料覆盖英语、法语、德语，17–20 世纪的报纸与印刷书籍。

任务的输入单位叫 **transcription unit**，官方定义逐字为：

> "The input consists of an OCR hypothesis and associated document metadata. The OCR hypothesis is the raw transcription of a transcription unit — a coherent piece of text providing sufficient context for correction, typically a paragraph or article."
> —— §2 Task Definition[^hipe]

> [!important] 这句话是本研究的入口
> **官方任务定义把上下文锁死在"一个段落或一篇文章"的级别。** 也就是说，"模型一次能看多少文本"在这个竞赛里是一个被固定的常量，而不是一个变量。我们要做的事情，正是把这个常量变成变量。

任务的约束性质，官方也写得很清楚——这**不是**自由文本生成：

> "systems are expected to restore intended word forms ... must not introduce content absent from the source"
> —— §2 Task Definition[^hipe]

### 1.2 指标：cMER

主指标是 **character-level Match Error Rate (cMER)**，micro-averaged：

$$\text{MER} = \frac{S + D + I}{H + S + D + I}$$

其中 $H$=命中、$S$=替换、$D$=删除、$I$=插入。与常规 CER 的关键区别是**插入项进了分母**，因此取值有界：

> "cMER is bounded in [0,1] because insertions appear in the denominator, reducing sensitivity to over-generation"
> —— §4.1 Metrics[^hipe]

官方 scorer 是开源的[^scorer]，我们的 `datasets/hipe_2026/dataset.py` 直接 import 它的 `norm()` 与 `mer_from_counts()`，字符对齐用 `jiwer.process_characters`——**指标实现是官方的，不是自己写的**。

### 1.3 官方结果与官方承认的开放问题

四支队伍、50 个 run：

> "Four teams submitted a total of 50 distinct runs, covering all official test datasets and languages."
> —— §5[^hipe]

三支队伍的路线（逐字）：

| 队伍 | 路线 | 原文 |
|---|---|---|
| Zakaria-ENSIAS | zero-shot prompting | "Their system performs zero-shot OCR post-correction using Qwen3-8B" |
| L3i | instruction tuning | "fine-tuned Qwen3-14B with instruction tuning on all available training pairs" |
| BnF-Mistral | continued pretrain + LoRA | "underwent continued pre-training on historical BnF documents...then fine-tuned using LoRA" |

—— 均出自 §5.2[^hipe]

> [!note] 观察
> 三条路线全部在**"怎么把模型调得更懂历史文本"**这一个维度上。没有任何一支队伍改变"模型能看到什么、能做什么操作"。操作面维度在这个任务上是**空白**的。

**官方 Table 7 的部分数字**（cMER，越低越好）：

| 数据集 | 未修复 baseline | 最佳系统 | 相对降幅 |
|---|---|---|---|
| icdar2017 (en) | 0.0260 | 0.0044 (BnF-Mistral run1) | −83% |
| dta19-**l0** (de, 低噪声) | **0.0040** | **0.0029** (BnF-Mistral run2) | **−27%** |
| dta19-l1 (de, ~3% CER) | 0.0240 | 0.0054 (BnF-Mistral run1) | −78% |
| dta19-l2 (de, ~7% CER) | 0.0546 | 0.0082 (BnF-Mistral run1) | −85% |

> [!warning] 这张表里藏着整个领域的痛点
> **在低噪声的 dta19-l0 上，冠军系统只把 cMER 从 0.0040 降到 0.0029。** 而在高噪声的 l2 上能降 85%。也就是说：**文本越干净，LLM 越帮不上忙，甚至容易改坏。** 这就是 over-correction 墙，而且它被官方数字量化了。

官方对此的表述（逐字）：

> "Overcorrection on low-noise inputs emerges as a recurring challenge"
> —— §1 Introduction[^hipe]

> "gains are strongest under moderate to high OCR noise, whereas low-noise historical text remains inherently sensitive to over-correction"
> —— §6 Results and Discussion[^hipe]

> "improving robustness across languages and domains, developing methods to control overcorrection and hallucination"
> —— §7 Conclusion（列为 future work）[^hipe]

> [!tip] 对我们的意义
> `dta19-l0/l1/l2` 共享**同一批 11 篇源文档、同样的页码抽样**，只有退化程度不同[^hipeinfo]。这是一条**现成的、零数据成本的噪声阶梯**，而且领域内最强的系统在它的低端明显失效。这是检验"操作面能否抑制 over-correction"的理想场地。

---

## 2. IDEA

### 2.1 直觉

人类修复一份文稿的方式不是"从头到尾重新抄一遍"，而是：

1. **先获得完整上下文**——通读全文，知道这是什么体裁、专有名词怎么拼、这一页和上一页什么关系；
2. **然后聚焦局部操作**——只在错的地方下笔，其余部分**物理上不经过手**。

现在的 LLM 后矫正流程把这两步都破坏了：为了让上下文可控，把文档切成小块（丢掉第 1 步）；为了拿到输出，让模型把整块重写一遍（丢掉第 2 步）。

### 2.2 机制假设：显式寻址 vs 隐式检索

如果要同时保住两步，有三种可能的操作面：

| # | 操作面 | 上下文 | 定位方式 | 输出 | 对应实现 |
|---|---|---|---|---|---|
| A | **全文重写** | 完整 | 无 | 整篇文本 | `rewrite` |
| B | **检索 + 局部替换** | 按需拉取 | **隐式检索**（grep/read 找片段） | 编辑指令 | `find_replace` |
| C | **标注块 + 结构化编辑** | 完整且**带块 id 标注** | **显式寻址**（直接引用块 id） | 编辑指令 | `patch` |

C 的核心是：**把整篇文档连同一套地址一起放进 context，让模型用自己的 attention 完成"聚焦"这一步，不需要额外的检索回合。**

具体形式是给模型一个带块标注的视图（`xml-ish` 标注，故意非良构以避免与文档自带 XML 混淆）：

```text
<x id="b1"\>
Thé quick brovvn fox jumps over the lazy dog.
</x>
<x id="b2"\>
Second line of the page, with anothcr error.
</x>
```

配一套按块操作的工具（`fn` 方言，一行一调用）：

```text
replace(b1, "Thé quick brovvn", "The quick brown")
replace(b2, "anothcr", "another")
```

> [!question] 三种操作面的差异到底是什么
> - A 让模型**承担了复制未变文本的责任**——每一个正确字符都要重新生成一遍，每一次生成都是一次犯错机会。
> - B 让模型**承担了检索的责任**——它必须先猜"错误可能在哪"，再去拉取，拉取窗口之外的上下文对它不可见。
> - C **两个责任都免掉**：未变文本由系统按块保真还原（不经过模型），定位由 attention 在完整上下文上直接完成。

### 2.3 三条可证伪的假设

- **H1（上下文交互）**：C 相对 A 的优势**随可见上下文增大而增大**。孤立小块上应当无差异；上下文越长、对话越久，差异越大。
- **H2（显式寻址优于隐式检索）**：C 优于 B，在**修复质量**与**token 成本**两个维度上都优。
- **H3（token efficiency）**：C 的输出只包含编辑指令而非全文，因此输出 token 更少、更省钱。

---

## 3. 证明逻辑：为什么必须在 HIPE 上做，而不是在 coding 上做

操作面这个变量，coding-agent 社区已经研究了两年（见 §7.2）。但他们的任务形态有两个结构性缺陷，使得"操作面是否影响质量"这个问题在那里**测不出来**：

**缺陷一：指标是二值的。** SWE-bench 类任务的结果是 pass / fail。一个补丁要么让测试通过，要么不通过。你无法问"这个修复改对了多少、改坏了多少"。

**缺陷二：编辑天然局部。** 修一个 off-by-one 只涉及几行，"重写整个文件"和"改那一行"在语义结果上是等价的——只要测试过了，中间过程改坏了多少无人知晓。

而 OCR 后矫正正好补上这两点：

| 维度 | coding 任务 | OCR 后矫正 |
|---|---|---|
| 结果 | 二值（pass/fail） | **连续**（cMER ∈ [0,1]） |
| "改坏了" | 不可测（测试过了就行） | **可测**（gold 逐字符对齐，S/D/I 可拆） |
| 未变文本 | 不参与评分 | **参与评分**（保真本身是任务目标） |
| 错误操作 | 只表现为 fail | **可单独计数**（op 应用失败率、over-correction rate） |

> [!important] 这就是"这个数据集不仅能评价结果好不好，还能评价有没有错误操作"的确切含义
> cMER 可以拆成 $S$ / $D$ / $I$ 三个分量。预测很具体：
> - **A（全文重写）的退化应主要来自 $D + I$** —— 漏抄、多写，也就是复制失败与内容漂移；
> - **C（结构化编辑）的错误应几乎全是 $S$** —— 替换选错；结构上不可能漏抄整段。
>
> 如果这个分解成立，一张表就把机制讲完了。**这在 coding 任务上根本无法测量。**

反过来说，coding 社区在这个变量上已经得出了一个**明确的、和我们相反的结论**（详见 §7.2），这正是本研究的对撞点。

---

## 4. 系统实现（一段话）

为了让"操作面"能作为受控变量，需要一套保证公平性与可审计性的基础设施。已完成，284 个离线测试通过：

- **保真 IR**：文件 → 分块 → 快照（内容寻址 store）→ 还原。三条保真等式作为验收：`write(read(b)) == b`、`concat(materialize(s, plan)) == s.text`、`reconstruct(build(blocks)) == s.text`。合起来就是**一份文件 ingest 后不做编辑直接写出，与原文件逐字节相同**——这保证了"未变文本不会被系统悄悄改动"。
- **公平性控制**：同一实验内模型配置、终止预算对各操作面一致；各臂拿到**同一份 `task.input` 与 `task.meta`**，instruction 完全相同，只有 `prompt_clause`（工具使用条款）随操作面不同，拼接顺序固定。
- **磁带（tape）与 replay**：每个 (task, 操作面) 的完整对话逐轮原子落盘。后处理代码改了想重算指标，用 `--replay` 从磁带重跑确定性后处理，**零 API 成本**。磁带被定义为不可再生资产，任何清理操作不得删除。
- **四个臂**：`noop`（不修复，锚点）、`rewrite`（A）、`find_replace`（B）、`patch`（C）。
- **三种形态**：`chunk`（逐块孤立单轮）、`seq`（一篇文档一场对话，每轮一块，无反馈）、`doc`（整篇一次单轮）。

> [!note] 为什么强调这些
> 它们不是贡献，是**让统计声明可信的前提**。审稿人会问"你确定 patch 臂的分数差不是你的还原代码造成的"——保真三等式就是这个问题的答案。（另外这里有过一次血的教训：早期版本的 `replace` 静默丢弃了 48 条修复中的 47 条，error=None、failed=False，**只有分数能暴露它**。这也是后来加 replay 与 op 应用率统计的动机。）

---

## 5. 目前的实验结果

### 5.1 实验设定

| 项 | 值 |
|---|---|
| 文档 | `icdar2017/periodical__eng_periodical-5`（英语，**11 个 chunk**） |
| 模型 | `volc-deepseek-v4-flash`（火山引擎 ark，thinking 默认开） |
| split | dev |
| instruction | 数据集默认（BLOCR SYSTEM_PROMPT 逐字副本） |
| 评分 | 官方 scorer；**doc / seq 形态的得分 = 切回 chunk 后逐块 cMER 的均值** |

> [!warning] 口径说明（重要，见 §6.2）
> 为复用官方逐条评分，doc 与 seq 形态的输出会**按分隔符切回 chunk、逐块评分、取均值**。因此三行的聚合口径一致（都是 chunk-mean），noop 在三行完全相同（0.0928）也正是这个原因。但 **chunk-mean ≠ 官方的 micro-averaged cMER**，所以本表的绝对值不能与官方排行榜对比。

### 5.2 修复质量（cMER ↓）

| 形态 | noop | rewrite (A) | patch (C) | C − A |
|---|---|---|---|---|
| **chunk 单轮**（11 块孤立） | 0.0928 [0.076, 0.108] | 0.0406 [0.027, 0.056] | 0.0413 [0.028, 0.055] | **+0.0007**（打平） |
| **seq 多轮**（1 场对话 × 11 轮） | 0.0928 | 0.0551 | **0.0325** | **−0.0226**（C 好 41%） |
| **doc 单轮**（整篇一次） | 0.0928 | 0.0473 | 0.0346 | **−0.0127**（C 好 27%） |

按"一场对话里累积多少上下文"排序（chunk 孤立 → seq 累积 → doc 全量），**两种操作面的曲线是反向的**：

```text
rewrite (A):  0.0406  →  0.0551  →  0.0473
              (孤立)     (累积)     (全量)
              ↑ 最好      ↑ 最差              退化 +35.7%

patch (C):    0.0413  →  0.0325  →  0.0346
              ↑ 最差      ↑ 最好              改善 −21.3%
```

> [!abstract] 这是目前最重要的观察
> **操作面在"孤立小片段"上不起作用；一旦对话累积历史或输入变长，操作面就从成本变量变成质量变量——而且方向相反：全文重写随上下文退化，结构化编辑随上下文改善。**
>
> 这个模式与 H1 的预测方向一致。

### 5.3 成本（total tokens / reasoning 占比）

| 形态 | rewrite (A) | patch (C) |
|---|---|---|
| doc 单轮 | 66k / 93% | 88k / 92% |
| chunk 单轮（11 块合计） | 293k / 98% | 329k / 98% |
| seq 多轮 | 218k / 92% | 248k / 96% |

把质量与成本合起来看——**每 100k token 换到的 cMER 降幅**：

| cell | cMER | Δ vs noop | 相对降幅 | tokens | **每 100k token 的降幅** |
|---|---|---|---|---|---|
| **rewrite × doc** | 0.0473 | −0.0455 | 49.0% | 66k | **0.0689** |
| **patch × doc** | 0.0346 | −0.0582 | 62.7% | 88k | **0.0661** |
| patch × seq | 0.0325 | −0.0603 | 65.0% | 248k | 0.0243 |
| rewrite × chunk | 0.0406 | −0.0522 | 56.2% | 293k | 0.0178 |
| rewrite × seq | 0.0551 | −0.0377 | 40.6% | 218k | 0.0173 |
| patch × chunk | 0.0413 | −0.0515 | 55.5% | 329k | 0.0157 |

> [!abstract] 第二个观察：不切块的 token 效率高出近 4 倍
> **doc 形态的 token 效率是任何切块流水线的约 3.8–4.4 倍。** `patch × doc` 拿到 62.7% 的降幅只花 88k token；`patch × seq` 多花 2.8× 的 token 只多换 0.0021 的 cMER——这是个坏交易。
>
> 这一条对领域是**反直觉且可操作**的：现有工作几乎全在 paragraph/page 粒度做（官方任务定义就是这么写的），因为大家默认"切块是必要的"。我们的数据说：**在有保真编辑面的前提下，别切。**

### 5.4 第三个观察：reasoning token 吃掉了 H3

**H3 被否证。** patch 的可见输出（编辑指令）比 rewrite 的可见输出（整篇文本）短 2–4×，但**账单更贵**（doc: 88k vs 66k；seq: 248k vs 218k；chunk: 329k vs 293k）。

原因在成本表最右列：**reasoning 占输出 token 的 92–98%**。patch 模式需要逐字匹配 `old` 串、验证块内是否存在该模式，模型想得**更多**。可见文本的压缩优势在思考噪声下无法兑现到账单。

一个副产品观察：**seq 比 chunk 便宜**（218k vs 293k；248k vs 329k），且 reasoning 占比从 98% 掉到 92/96%。**给模型对话上下文，它每个单元想得更少。** 这条可以接上 *Coupling Tax*[^coupling] 与 *Thinking Costs Tokens*[^thinkcost] 那一支文献。

> [!important] 为什么这个负结果值钱
> "编辑格式比全文重写省 token" 是 coding-agent 社区的标准论断，而**我检索到的两篇最相关的 edit-format 论文都没有把 reasoning token 与可见输出 token 分开计账**（见 §7.2 的核实结论）。在 reasoning 模型成为默认的今天，这个标准论断可能已经失效——这本身是一个可以独立成节的发现。

---

## 6. 已知局限（必须先自己说）

> [!danger] 这一节比结果那一节更重要
> 下面每一条都可能推翻 §5 的解读。前三条**零 API 成本就能查清**，应当在烧任何新 token 之前完成。

### 6.1 n = 1 文档

doc 与 seq 两行都是**一篇文档**。chunk 行的 CI 是同一篇文档内 11 个 chunk 的 bootstrap——那是 **within-document** CI，**不支持任何跨文档推广**。

**但 seq 行其实不是 n=1。** `src/agent/sequential.py` 里，`rewrite_seq` 的 `tool_state["outputs"]` 是一个 per-chunk 的 list，`patch_seq` 是 per-chunk 的 `stores`；磁带里每轮 completion 都在。所以：

- seq 的 11 个单元输出可以**单独评分**，与 chunk 单轮的 11 个分数**一一配对** → 立刻得到 seq−chunk 差值的配对 bootstrap CI（n=11）；
- 更值钱的是：**轮次序号 1..11 给出一条对话内漂移曲线**。假设很明确——rewrite 的 cMER 随轮次上升（历史里堆着自己的重写，drift + distractor），patch 不上升。

**这一步零 token，产出是全文最强的一张图。优先级最高。**

### 6.2 聚合口径有一个需要确认的分支

`dataset.py` 的 doc 级评分逻辑：把预测按分隔符切回 chunk，若**切出的块数与 gold 单元数相等**则逐块评分取均值；若**不相等**（模型改坏了拼接结构），则回退为整篇 micro cMER 并置 `chunks_aligned = 0.0`。

这个 guard 设计是对的，但它意味着：**如果某个 cell 走了回退分支，它的 cMER 与其他 cell 不是同一个指标**（chunk-mean vs micro，在页长跨度 65–7908 字符的数据上可以差很多）。

> [!warning] 必须查的一个数
> **doc / seq 的 6 个 cell 各自的 `chunks_aligned` 是多少？**
> 如果 `rewrite × seq`（0.0551，最差的 cell）是 0 而 `patch × seq`（0.0325，最好的 cell）是 1，那这两个数不在同一个尺度上，§5.2 的核心比较**不成立**。
>
> 反过来，如果全是 1，那结论稳固，而且"rewrite 更容易改坏拼接结构"这件事需要单独作为一个 finding 报出来。

### 6.3 噪声区间偏高——我们在最容易的区间做实验

我们的 noop = **0.0928**，而官方 icdar2017 (en) 的 baseline 是 **0.0260**，甚至高于 dta19-l2 的 0.0546。差异来自 split（dev vs test）、单文档方差、以及 chunk-mean vs micro 的聚合差异。

后果有两个：

1. **绝对值不可与排行榜比较。** 我们最好的 cell（0.0325）与官方最佳（0.0044）差 7 倍，但口径、模型规模（小 flash 模型、zero-shot、无 fine-tune）、split、样本量全都不同。**论文里必须明确声明比较的是臂之间，不是 SOTA。**
2. **更要紧的是**：cMER≈0.09 属于官方所说的 "moderate to high OCR noise" 区间——正是 LLM 修复**最容易见效**的区间。而 over-correction 问题住在低噪声端。**我们目前的证据完全没有触及那个区间。**

### 6.4 H2 完全没有证据——最大的缺口

`find_replace` 臂（操作面 B，即 coding-agent 的标准 `str_replace` 模式）**代码里有，但一次都没跑过**。

这意味着 §2.3 的 H2——"显式寻址优于隐式检索"——目前**零证据**。而这恰恰是审稿人的第一个问题：**"你的 patch 不就是加了壳的 str_replace 吗？"** 没有这个臂，这个问题无法回答。

### 6.5 单模型、单 reasoning 模式

reasoning 占输出的 92–98%。**目前所有"操作面效应"都与"thinking 模式"混在一起，无法归因。** §5.4 的 token 结论现在严格来说是"关于 deepseek-v4-flash 思考习惯的结论"，不是"关于编辑格式的结论"。

### 6.6 patch 的静默失败未统计

`sequential.py` 中：

```python
except (surface.ParseError, surface.SurfaceError):
    pass  # 单机会语义：该单元保留原文；错误不回灌（口径对齐 rewrite_seq）
```

某单元的 patch 解析或应用失败 → 该单元原文照抄 → 照常评分。**现在无法区分"模型判断不用改"和"模型的编辑被拒了"。**

如果 11 个单元里有若干个是静默失败保留原文，patch 的 0.0325 就有另一种解释：**patch 赢是因为它"做得更少"（保守 = 少 over-correct）。** 这依然有意思（正好对上官方点名的 over-correction 问题），但**机制完全不同，论文也完全不同**。

需要报的三个数（每臂 × 每形态）：尝试的 op 数、成功应用的 op 数、原文未变的单元数（并区分"模型没改"与"应用失败"）。**磁带里存着完整 patch 文本，零成本可算。**

### 6.7 其他

单语言（英语）、单子集（icdar2017）、`seq` 采用**单机会无反馈**口径（为对齐 rewrite 的公平性选择）。最后一条会被问："patch 的卖点难道不是带错误反馈的迭代修复吗？"——需要在论文里正面回答，不能只写在代码注释里。

---

## 7. 文献定位：这个 idea 的 potential 在哪

> [!note] 引文说明
> 下列引文均由自动化工具从各论文的 HTML 全文中抽取，并标注了出处小节。标 ✅ 的取自论文 HTML 正文（高置信）；标 ⚠️ 的来自二手来源或格式受损，**建议核对原文**。§8.3 列出了需要下载原始 PDF 的清单。

### 7.1 相邻文献的四块地，以及它们各自的边界

| 块 | 代表工作 | 它做了什么 | **它的边界（= 我们的空间）** |
|---|---|---|---|
| **A. LLM 后矫正** | HIPE 竞赛[^hipe]、No Free Lunches[^nofree]、多模态后矫正[^multimodal] | 模型适配维度：prompting / fine-tune / continued pretrain / 加图像 | 操作面固定为**全文重写**；上下文固定为**单个 transcription unit** |
| **B. 编辑表示（NLP 侧）** | GECToR[^gector]、Seq2Edits、GEC 综述[^gecpillars]、Beyond the Chat[^exectext] | 论证了"预测编辑操作优于重写整句"；后者让 LLM 产出显式可执行编辑列表 | 前者是**模型架构**（sequence tagging）而非 **agent 工具契约**；后者目标是**人类可验证性**，不是自动化质量与 token 的受控比较 |
| **C. 操作面 / ACI（coding 侧）** | SWE-agent[^sweagent]、execute_code regime[^regime]、To Diff or Not to Diff[^todiff]、SWE-Edit[^sweedit]、Scaffold Effect[^scaffold] | 把操作面当研究变量，做了大量 ablation | 全部在 **code 域**：指标二值、编辑天然局部、**且已得出"操作面不影响能力"的结论** |
| **D. 文档委托的保真崩塌** | DELEGATE-52[^delegate] | 证明 LLM 长流程会把文档改坏，且**给工具反而更差** | 用的是朴素 file-writing 工具，**无 gold、无连续指标、无受控操作面对比** |

### 7.2 最关键的对撞：coding 域已发表"操作面不影响能力"

这是本研究最重要的对话对象。`execute_code regime` 研究[^regime]在同一个 harness 上交叉了三种工具面（baseline / bash-only / code-only），按任务 regime 分层（computation n=93 / modification n=100），结论逐字为：

> "Pass rates differ by less than three percentage points across every cell while costs swing 20–40%."
> —— §6.3 Failure-cost and capability invariance ✅[^regime]

> "The straightforward interpretation is that tool restriction is a harness-efficiency axis orthogonal to model capability: the model solves the task with any reasonable interface; the surface changes the path, not the answer."
> —— §6.3 ✅[^regime]

成本降幅（原文数字有 HTML 格式损坏，此处取整）：

> "Artifact/Claude (−24.6%, p=7.37×10⁻¹⁴) and SWE-bench/Codex (−19.9%, p=2.02×10⁻⁹)"
> —— §5.1 ⚠️（原始串为 `−24.595857141034 71%`，疑 HTML 渲染问题，需核对）[^regime]

> [!abstract] 我们的位置
> **我们不是重复它，我们是给它划边界。**
>
> 他们的结论在 code 域成立，因为那里的任务是 pass/fail 二值、编辑天然局部。我们的初步结果说：在**有连续保真指标、且未变文本参与评分**的任务上，**一旦上下文累积，操作面就影响能力**（seq 形态下 41% 的相对差距）。
>
> 这个"解释别人为什么得到那个结论、并给出它失效的条件"的姿态，比单纯报一个新数字强得多。

同时，他们的 scope 限定（逐字）：

> "Single-shot, internal-surface scope. Multi-shot prompting, scaffold evolution, and external MCP tool surfaces ... are out of scope."
> —— §Limitations ✅[^regime]

**并且**（这一条对 §5.4 很关键）：

> 该论文的成本口径为 `cost = input_tokens·r_in + output_tokens·r_out`（§3.5 Cache isolation and cost reporting），**未将 reasoning token 与可见输出 token 分开计账**。✅[^regime]
>
> 同样地，`To Diff or Not to Diff?`[^todiff] 也**未在 token 计账中区分 reasoning token**。✅

> [!tip] 结论：§5.4 的角度是原创的
> 两篇最相关的 edit-format / 操作面论文都没拆 reasoning token。**"编辑格式省 token 的经典论断在 reasoning 模型上失效"这个发现目前没有被占。**

### 7.3 ACI 作为研究变量的正统性（我们站在这条线上）

SWE-agent[^sweagent] 是这条线的奠基工作，其定义与设计原则逐字：

> "We refer to the interface LM agents use to interact with computers as the agent-computer interface (ACI)."
> —— §2 The Agent-Computer Interface ✅[^sweagent]

> ACI "specifies both the commands available to the LM and how the environment state is communicated back to the LM."
> —— §2 ✅[^sweagent]

四条设计原则（§2，✅）：

| 原则 | 原文 |
|---|---|
| Simplicity | "Actions should be simple and easy to understand for agents." |
| Efficiency | "Actions should be compact and efficient. Important operations...should be consolidated into as few actions as possible." |
| Concise Feedback | "Environment feedback should be informative but concise...without unnecessary details." |
| Guardrails | "Guardrails mitigate error propagation and hasten recovery." |

ACI ablation（§5.1 / Table 3，⚠️ 数字建议核对）：

| 配置 | resolve rate |
|---|---|
| edit **with** linting | 18.0% |
| edit without linting | 15.0%（−3.0 pp） |
| file viewer 100 行 | 18.0% |
| file viewer 30 行 | 14.3%（−3.7 pp） |
| file viewer 全文件 | 12.7%（−5.3 pp） |

并且他们明确把 ACI 研究本身当作值得推进的方向：

> "We hope the further study of ACIs can also make principled use of and contribute to our understanding of language models and agents, analogous to the synergy between human-computer interaction (HCI) and psychology."
> —— §7 Discussion ✅[^sweagent]

> [!note] 注意 file viewer 那一行
> **"全文件"比"100 行窗口"差 5.3 pp**——在 code 域，给模型更多上下文反而更糟。而我们的 doc 形态结果相反。这个矛盾值得在论文里正面处理：可能的解释是 code 任务的相关上下文是**稀疏且跨文件**的，而 OCR 修复的相关上下文是**稠密且局部连续**的。

### 7.4 编辑格式的已知结论（我们必须与之对话）

`To Diff or Not to Diff?`[^todiff] 比较三种 diff 风格（§Appendix A，✅）：

| 风格 | 原文定义 |
|---|---|
| Hunk rewrite | "directly specifies the target code block to be rewritten" |
| Unified diff-like | "incorporates context lines alongside addition and deletion markers" |
| Search/replace | "utilizes specific delimiters to separate the original block from its replacement" |

关键发现：

> "the inclusion of unchanged context lines often disorients the model compared to the simpler binary logic of addition and deletion"
> —— §Appendix A / Table 5 ✅[^todiff]

> "the search/replace style and the hunk rewrite style demonstrate comparable accuracy"
>
> "the search/replace style can fail to patch if the source code contains characters identical to its special delimiters. This potential for catastrophic failure constitutes a direct violation of the reliability requirements"
> —— §Appendix A ✅[^todiff]

> [!tip] 我们的方言正好绕开了这个失效模式
> 我们的 `fn` 方言用**函数调用 + JSON 字符串**承载参数（转义与多行由 JSON 负责），且块地址是**显式 id 而非分隔符匹配**。上面那条"分隔符与源码字符冲突导致灾难性失败"的风险在我们的设计里结构上不存在。这是一个可以写进 Method 的设计论证。

`SWE-Edit`[^sweedit] 则做了 find-replace 与 whole-file-rewrite 的自适应选择，报告 "raises resolve rate by 2.1 pp and cuts inference cost by 17.9%"（⚠️ 需核对）。

### 7.5 我们的动机已被独立验证（这篇是弹药，不是对手）

`DELEGATE-52`[^delegate] 构造了 52 个专业领域、310 个工作环境、每个模拟 20 轮交互，用 round-trip backtranslation 测量文档腐蚀：

> "even frontier models (Gemini 3.1 Pro, Claude 4.6 Opus, GPT 5.4) corrupt an average of 25% of document content by the end of long workflows"
> —— §Abstract ✅[^delegate]

> "The four tested models perform worse when operated agentically with tools than without, incurring an average additional degradation of 6% by end of simulation."
> —— §4.2 Agent (With Tools) vs. LLM (Without Tools) ✅[^delegate]

他们给的工具是什么：

> "we implemented a basic agentic harness with file reading, writing, and code execution tools"
> —— §4.2 ✅[^delegate]

腐蚀的形态：

> "Instead, they maintain near-perfect reconstruction in some rounds, and experience critical failures in a few rounds, typically losing 10-30+ points in a single round trip. These sparse critical failures explain about 80% of total document degradation we observe."
> —— §5 Analysis - Critical Failures ✅[^delegate]

> "document size and interaction length compound multiplicatively: the degradation from increased document size snowballs over the course of the interaction."
> —— §4.3 Document Size Effect ✅[^delegate]

> [!abstract] 这篇论文替我们证明了问题存在，同时留下了我们要填的坑
> - 它证明：**LLM 长流程会把文档改坏，而且给它朴素的文件读写工具反而更糟**（这正是我们的操作面 B 的失败预期）。
> - 它没有：gold、连续指标、受控的操作面对比。它只能定性描述"腐蚀"，无法说"改坏了多少、哪种操作面能抑制"。
> - **我们有 gold，我们能画出那条曲线。** 而且我们可以检验："换成保真编辑面（操作面 C），这条曲线能不能压平。"
>
> 它的 "sparse critical failures 解释 80% 的腐蚀" 与 "document size × interaction length 乘性复合" 两条，正是我们 §6.1 计划的**轮次漂移曲线**要直接对话的对象。

### 7.6 与我们动机最接近的竞争工作

`Post-OCR Correction Using LLMs with Constrained Decoding`[^constrained]：在 **decoding 层**加入 OCR 输入与生成输出之间的字符级相似度约束，引导模型贴近原文结构。

> [!important] 动机相同、手段不同——这是必须正面对话的对象
> 它和我们解决的是同一个问题（**防止 LLM 偏离原文**），但作用层不同：
> - 它在 **decoding 层**约束（改采样）；
> - 我们在 **操作面层**约束（改模型能做什么动作）。
>
> 我们的优势是**不需要访问 logits**——纯 API 模型也能用；它的优势是无需模型遵循任何格式。这个对比应当写成 Related Work 的一个段落。
>
> ⚠️ 这篇我没能取到全文（Research Square 返回 403），**引文与作者信息待核实**，见 §8.3。

同一"不同层解决同一问题"的还有 `Copy-as-Decode`[^copydecode]：从**解码侧**处理"未变文本要重新生成"的开销，报告在测试语料上 round-trip exact-match 完美且 token 预算最低。三者可以排成一张对照表——**decoding 层约束（constrained decoding）/ decoding 层复制（copy-as-decode）/ 操作面层约束（本工作）**——这张表本身就是一个清晰的定位论证。

### 7.7 空地清单：我检索后确认没有人做过的事

| # | 空地 | 检索结论 |
|---|---|---|
| 1 | **保真约束任务上的操作面受控实验** | 未检索到。code 域有大量此类工作，但指标二值；OCR 域有连续指标，但操作面从未变过 |
| 2 | **操作面 × 上下文长度的交互** | 未检索到。code 论文按 task regime 分层，没有按"同一份文本、切/不切"配对 |
| 3 | **操作面作为 over-correction 的结构性抑制手段** | 未检索到。官方点名的问题，现有解法在 decoding 层或 prompt 层 |
| 4 | **reasoning token 解构下的编辑格式效率论** | **已核实**：两篇最相关的论文均未拆 reasoning token（§7.2） |
| 5 | **"切分粒度的成本杠杆大于编辑格式"** | 未检索到有人报告过。我们的数据：同一文本切成 11 块，out token 涨 4.6×，而换编辑格式只涨 1.36× |
| 6 | **给 LLM 超过一个 transcription unit 的上下文是否有用** | 官方任务定义就锁在 unit 级（§1.1），竞赛四支队伍无人越界 |

> [!warning] 检索的边界（诚实声明）
> 已做：arXiv + ACL Anthology + ICDAR 方向共 9 轮关键词检索 + 7 篇论文全文取证，覆盖 (a) LLM post-OCR correction 2025–2026、(b) edit format / diff vs whole-file、(c) ACI / harness / scaffold ablation、(d) GEC seq2edit、(e) reasoning token 成本、(f) 文档编辑保真、(g) agentic OCR。
>
> **未做**：ICDAR / DAS / TPDL / JCDL 的完整 proceedings 穷举；HIPE 竞赛综述正文中四支队伍方法的逐段细读（只取到 §5.2 的摘要级引文）；非英语文献。**在投稿前这三项必须补。**

---

## 8. 下一步计划

### 8.1 P0：零 API 成本，从已有磁带算（应当在烧任何新 token 之前完成）

| # | 动作 | 产出 | 对应局限 |
|---|---|---|---|
| P0-1 | 把 seq 磁带拆成 **per-unit 分数**，与 chunk 单轮**一一配对** | seq−chunk 差值的配对 bootstrap CI（n=11） | §6.1 |
| P0-2 | 画 **cMER × 轮次序号（1..11）** 曲线，两臂对照 | 漂移机制的直接证据；与 DELEGATE-52 对话的那张图 | §6.1 |
| P0-3 | 查 doc / seq 六个 cell 的 **`chunks_aligned`** | 确认三行是否同尺度 | §6.2 |
| P0-4 | 统计每臂每形态的 **op 尝试数 / 成功应用数 / 原文未变单元数**（区分"没改"与"应用失败"） | 排除"patch 赢是因为做得少" | §6.6 |
| P0-5 | 把 cMER 拆成 **S / D / I** 分量 | §3 那个机制预测的直接检验 | 机制证据 |

> [!danger] P0-2 是一个 go / no-go 检查点
> 如果 rewrite 的漂移曲线**不上升**，§5.2 的整个故事就要改写。**在花 40M+ token 之前必须先知道这件事。**

### 8.2 P1：需要烧 token 的实验（按性价比排序）

**P1-1｜dta19 噪声阶梯（建议作为主实验）**

`dta19-l0/l1/l2` 共享同一批 11 篇源文档与同样的页码抽样。一次实验同时拿到三样东西：**噪声因子 + 跨文档方差（11 篇）+ 跨语言（德语）**。

设计：`操作面 {noop, rewrite, find_replace, patch} × 形态 {chunk, seq, doc} × 噪声 {l0, l1, l2} × 11 篇文档`

预测（可证伪）：**低噪声 l0 上 rewrite 的 over-correction 惩罚最重、patch 优势最大；高噪声 l2 上两者拉平。** 若成立，就是**用操作面的角度回答了官方点名的开放问题**（官方数据：l0 上冠军系统只改善 27%）。

**P1-2｜补 `find_replace` 臂 —— H2 的唯一证据来源**

只在 `seq` 与 `doc` 两格补（chunk 已知打平，省 token）。**没有这个臂，"patch 不就是加了壳的 str_replace"这个问题无法回答。**

**P1-3｜icdar2017 英语跨文档复现，n ≥ 30**

⚠️ **先花五分钟数一下 dev split 上 icdar2017 en 到底能分出多少篇 doc 级任务**（188 行 chunk 分成多少个源文档？），再决定是否需要拉 train split 或法语进来。**这类"没先验证数据假设就开跑"的错误我们已经犯过一次**（曾按错误的分组键跑了一整轮 doc 实验，结果每个 doc 恒为单 chunk）。

**Token 预算估算**（按当前单篇实测外推）：

| 方案 | 每篇 token | 篇数 | 合计 |
|---|---|---|---|
| 2 臂 × 3 形态 | ~1.24M | 30 | ~37M |
| + find_replace 两格 | ~1.55M | 30 | ~46M |
| dta19 全设计（4 臂 × 3 形态 × 3 噪声） | ~2.3M | 11 | ~76M |

若预算不足，**砍形态不砍样本**：保留 chunk 与 doc 两个极端 + seq，样本量优先。

**P1-4｜≥3 个模型，且至少一个非 reasoning 模型**

没有这一条，§5.4 的 token 结论无法从"这个模型的性质"升级为"编辑格式的性质"。

### 8.3 需要你帮忙的事（我取不到的材料）

| # | 材料 | 为什么需要 | 怎么做 |
|---|---|---|---|
| 1 | `Post-OCR Correction with Constrained Decoding` 全文 | §7.6 那个"动机相同、手段不同"的对比，目前引文与作者未核实 | Research Square 返回 403；请从 [researchsquare.com/article/rs-6823036/v1](https://www.researchsquare.com/article/rs-6823036/v1) 下 PDF |
| 2 | HIPE 综述 **Table 7 完整版** + 结果图 | §1.3 我只取到 icdar2017-en 与 dta19 三级；其余子集/语言的 baseline 与最佳值需要补全 | [arxiv.org/abs/2607.08143](https://arxiv.org/abs/2607.08143) 下 PDF 或 TeX；表与图请截图 |
| 3 | HIPE 综述 **§5.2 四支队伍方法的完整段落** | 要断言"没人动过操作面"，必须逐段读完，不能只看摘要级引文 | 同上 |
| 4 | `DELEGATE-52` 的**退化曲线图** | 那张图与我们 P0-2 要画的轮次漂移曲线直接可比，放在一起最有说服力 | [arxiv.org/abs/2604.15597](https://arxiv.org/abs/2604.15597)，请截图 |
| 5 | `SWE-agent` **Table 3** | §7.3 的 ablation 数字标了 ⚠️，需核对 | [arxiv.org/abs/2405.15793](https://arxiv.org/abs/2405.15793) |
| 6 | `execute_code regime` **§5.1 成本表** | §7.2 的数字原始串疑有 HTML 渲染损坏 | [arxiv.org/abs/2607.10569](https://arxiv.org/abs/2607.10569) |

### 8.4 明确不做

- **MCP / 外部 harness（codex）横向对比。** 外部 harness 含其自有隐藏提示词与内部流程开销，与 in-house loop 不 token 对账。会把讨论带进"你在比模型还是比 harness"的泥潭。
- **再加第四种形态**（带反馈的 seq、rewrite_pieces）。除非 P0-4 查出 patch 在大量单元上是静默应用失败——那时补**一格**带反馈的 patch_seq，用来证明"patch 的优势不是靠保守"。
- **追竞赛排行榜。** 我们的贡献是受控实验，不是 SOTA。
- **堆通用指标**（BLEU / chrF 等）。只加 §8.1 说的那几个中介指标。

### 8.5 投稿定位（供讨论）

| 档位 | 需要什么 |
|---|---|
| **CHR / LaTeCH-CLfL / ICDAR-HIP workshop** | P0 全部 + P1-1（dta19 噪声阶梯）。HIPE 综述 2026-07 才出，现在是这个数据集的论文窗口期，占坑成本低 |
| ***ACL / EMNLP Findings** | 上面 + P1-2（find_replace）+ P1-3（n≥30 跨文档）+ ≥2 模型 |
| **主会 / ICDAR 2027 主会 / DAS** | 上面 + P1-4（≥3 模型含非 reasoning）+ 交互效应在多模型上复现。ICDAR/DAS 方向对 §4 的系统性贡献（保真三等式、可审计磁带、零成本 replay）更宽容 |

---

## 9. 一句话总结（给讨论用）

> 官方任务定义把上下文锁在单个 transcription unit，竞赛的所有创新都在模型适配维度；coding-agent 社区在操作面维度做了大量工作，但已得出"操作面只影响成本、不影响能力"的结论，因为他们的指标是二值的。**我们站在这两条线的交点：在一个有连续保真指标、且未变文本参与评分的任务上，检验操作面是否影响能力。初步结果说：在上下文负载下，影响，而且方向与 coding 域相反。**

---

## 引用

[^hipe]: **ICDAR 2026 HIPE-OCRepair Competition on LLM-Assisted OCR Post-Correction for Historical Documents.** arXiv:2607.08143. https://arxiv.org/abs/2607.08143 ——本项目使用的数据集与指标的权威来源。引文取自 HTML 版正文（§1 / §2 / §4.1 / §5 / §5.2 / §6 / §7 与 Table 7）。

[^scorer]: **HIPE-OCRepair-scorer**（官方评分器）. https://github.com/hipe-eval/HIPE-OCRepair-scorer ——`datasets/hipe_2026/dataset.py` 直接 import 其 `norm()` 与 `mer_from_counts()`。

[^hipeinfo]: 本仓库 [[HIPE_info]]（`Docs/HIPE_info.md`）：基于 `related_source/HIPE-OCRepair-2026-data-0.9.5/data/v0.9` 的实读统计（2026-09-02），含 dta19 三退化级共享同一批 11 篇源文档与页码抽样的对照表。

[^sweagent]: **SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering.** NeurIPS 2024. arXiv:2405.15793. https://arxiv.org/abs/2405.15793 ——ACI 概念的奠基工作。引文取自 ar5iv HTML（§2 / §5.1 / Table 3 / §7）。

[^regime]: **When Does Restricting a Coding Agent to `execute_code` Help? A Regime-Stratified Study.** arXiv:2607.10569. https://arxiv.org/html/2607.10569v1 ——本研究最重要的对撞对象。引文取自 HTML 正文（§3.5 / §5.1 / §6.3 / Limitations）。

[^todiff]: **To Diff or Not to Diff? Structure-Aware and Adaptive Output Formats for Efficient LLM-based Code Editing.** arXiv:2604.27296. https://arxiv.org/html/2604.27296v1 ——编辑格式的系统比较。引文取自 HTML 正文（Appendix A / Table 3 / Table 5 / Abstract）。

[^sweedit]: **SWE-Edit: Rethinking Code Editing for Efficient SWE-Agent.** arXiv:2604.26102. https://arxiv.org/abs/2604.26102 ——find-replace 与 whole-file-rewrite 的自适应选择。⚠️ 数字来自摘要级摘录，需核对。

[^scaffold]: **The Scaffold Effect in Coding Agents: Harness Choice as a Hidden Variable.** arXiv:2607.22585. https://arxiv.org/html/2607.22585 ——"harness 是隐藏变量"的直接论证，同期还有 *Measuring Harness-Induced Belief Divergence in Multi-Step LLM Agents*（arXiv:2607.04528）与 *Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures*（arXiv:2604.03515）。

[^delegate]: **LLMs Corrupt Your Documents When You Delegate**（DELEGATE-52）. arXiv:2604.15597. https://arxiv.org/html/2604.15597v1 ——我们动机的独立验证。引文取自 HTML 正文（Abstract / §4.2 / §4.3 / §5）。

[^coupling]: **The Coupling Tax: How Shared Token Budgets Undermine Visible Chain-of-Thought Under Fixed Output Limits.** arXiv:2605.07686. https://arxiv.org/html/2605.07686v1 ——reasoning 与答案共享输出预算的结构性问题，与 §5.4 同频。

[^thinkcost]: **Thinking Costs Tokens: When More Structure is Worth the Price.** arXiv:2608.27506. https://arxiv.org/abs/2608.27506 ——reasoning 开销与结构化推理的性价比阈值。

[^nofree]: **OCR Error Post-Correction with LLMs in Historical Documents: No Free Lunches.** arXiv:2502.01205. https://arxiv.org/abs/2502.01205 ——LLM 后矫正的边界。已核实引文："while modern LLMs show promise in reducing character error rates (CER) in English, a practically useful performance for Finnish was not reached."（英语/芬兰语历史语料）⚠️ 输出格式（是否全文重写）未在可取到的部分中说明。

[^multimodal]: **Multimodal LLMs for OCR, OCR Post-Correction, and Named Entity Recognition in Historical Documents.** arXiv:2504.00414. https://arxiv.org/abs/2504.00414 ——指出既有 LLM 后矫正工作"exclusively text-based"，转而把噪声转写与原图一起喂进多模态 LLM。⚠️ 引文为二手摘录。

[^constrained]: **Post-OCR Correction Using Large Language Models with Constrained Decoding.** Research Square, rs-6823036/v1. https://www.researchsquare.com/article/rs-6823036/v1 ——动机最接近的竞争工作（decoding 层约束 vs 我们的操作面层约束）。⚠️ **全文取回失败（HTTP 403），作者/年份/具体数字全部待核实**，见 §8.3-1。

[^gector]: **GECToR – Grammatical Error Correction: Tag, Not Rewrite.** BEA 2020. https://aclanthology.org/2020.bea-1.16.pdf ——edit-based sequence tagging 路线的代表；与我们的区别是"模型架构"而非"agent 工具契约"。

[^gecpillars]: **Pillars of Grammatical Error Correction: Comprehensive Inspection Of Contemporary Approaches In The Era of Large Language Models.** arXiv:2404.14914. https://arxiv.org/abs/2404.14914 ——seq2seq 与 seq2edit 两条路线的综述性对比。

[^exectext]: **Beyond the Chat: Executable and Verifiable Text-Editing with LLMs.** arXiv:2309.15337. https://arxiv.org/abs/2309.15337 ——让 LLM 产出显式可执行编辑列表并在编辑器界面中呈现、供用户逐条接受/拒绝。与我们最接近的**交互式**先行工作，但目标是人类可验证性，不是自动化质量与 token 效率的受控比较。

[^copydecode]: **Copy-as-Decode: Grammar-Constrained Parallel Prefill for LLM Editing.** arXiv:2604.18170. https://arxiv.org/html/2604.18170v1 ——从解码侧解决"未变文本要重新生成"的开销问题；报告在测试语料上 round-trip exact-match 完美且 token 预算最低。与我们的操作面思路互补（可作为 §7.6 之外的第二个"不同层解决同一问题"的对照）。

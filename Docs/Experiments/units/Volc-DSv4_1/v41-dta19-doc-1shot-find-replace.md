# v41-dta19-doc-1shot-find-replace

> 状态：已完成（2026-09-18）

实验单元：**doc 级、find_replace、1 doc per session、1 shot** —— 与
`../dta19-doc-1shot-find-replace` **配置逐字相同**，唯一变量是**模型版本**
（`volc-deepseek-v4-flash` → `volc-deepseek-v4.1-flash`，即火山模型名
`deepseek-v4-flash` → `deepseek-v4.1-flash`）。

跨模型复现序列中的位置：volc deepseek-v4-flash（蓝本）→ Openrouter GLM 5.3 Flash
→ Packy Grok 4.6 → **本批次 = 同端点模型版本升级**。这是历次复现中控制最严的
一次：**同端点**（火山 `https://ark.cn-beijing.volces.com/api/plan/v3`）、同协议
（`openai-response`）、同上下文声明（1024k，信息性）、同输出预算
（`output_length=393216`，384k，显式下发为 `max_output_tokens`）——连端点都不变，
只有模型版本。本批次回答的问题是：**版本升级是否改变编辑接口层面的结论**
（蓝本批次报告 `../report/2026-09-08-doc-1shot.md` 的「缺口」节指出全部结论目前
是单模型的性质）。

## Tool

- 工具集：`src/agent/standard.py::FindReplaceAnthropicToolSet`（注册键 `find_replace_anthropic_style`）
- 配置：`configs/toolsets/find_replace_anthropic_style.toml`（`max_turns=1`）
- 视图组件：`src/view/present.py::file_header`（`--- [Text: text] ---` 抬头）+ 纯原文

`find_replace(text, "old", "new")`：`old` 在整个 path 内必须恰好出现一次，
0 或 >1 都**拒绝执行并回报冲突数**（对齐 Anthropic `str_replace`；与旧
`find_replace` 臂的 replace-all 语义不同）。tool_state 持有当前文本（无 IR）。
1-shot 下被拒绝的调用没有重试机会，直接作废。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + FIND_REPLACE_ANTHROPIC_CLAUSE
       + ONE_SHOT_NOTICE_TOOLS
```

提示词组件列表：

**BLOCR instruction**（任务指令，全实验共享）：`datasets/hipe_2026/instruction.md`

```txt
You are an expert in historical OCR post-correction for newspapers and books from the 17th to 20th century in English, French and German.

You will receive a single OCR transcription unit to correct, preceded by its language.

Your task:
1. Correct OCR errors in "ocr_hypothesis" and write the result into a new field "ocr_postcorrection_output"
2. Do NOT alter person names or place names
3. Correct only within the given "language" — do not translate
4. Preserve or restore accented characters correctly
5. Fix four classes of common historical OCR errors:
- Over-segmentation: words broken across lines; hyphens replaced with spaces e.g. "before the follow ing morning" -> "before the follow-ing morning"
- Under-segmentation: missing spaces between words e.g. "Rich oldSwarth LAND" -> "Rich old Swarth LAND"
- Misrecognized character: e.g. "aſter" -> "after"; "ar.d" -> "and"
- Missing character: e.g. "er a good deal" -> "After a good deal"
6. If too ambiguous, copy ocr_hypothesis unchanged
```

**FIND_REPLACE_ANTHROPIC_CLAUSE**（本臂与实验2 两个 find_replace 臂同源）：
`src/agent/standard.py`

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path`
- find_replace(path, "old", "new") — replace "old" with "new" in `path`. "old" must be copied VERBATIM from the text and must match EXACTLY ONE place in `path`. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```

**ONE_SHOT_NOTICE_TOOLS**（全部 neo 工具臂共有，永远在最后）：`src/agent/standard.py`

```txt
You have only ONE chance: this task gives you a single response — no feedback, no retry, no second turn.
Emit ALL your calls in this one response, with done() as the last line.
```

### 每轮对话

1-shot：只有第一轮。模型响应后不再有任何轮次——调用执行完即 extract
（未以 `done()` 收尾记 `budget_exceeded`，产出照常评分）。

第一轮：

- system: 上方装配的三段拼接
- user: `--- INPUT (language: de) ---` + `--- [Text: text] ---` + 纯原文
  + `--- END OF INPUT ---`，由 `present_input` 产出
- assistant（期望形态）：一口气给出全部调用，`done()` 收尾，例如

```txt
find_replace(text, "brovvn", "brown")
find_replace(text, "Thé quick", "The quick")
done()
```

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,find_replace_anthropic_style `
    --model volc-deepseek-v4.1-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/v41-dta19-doc-1shot-find-replace --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_anthropic_style \
    --model volc-deepseek-v4.1-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/v41-dta19-doc-1shot-find-replace --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_anthropic_style` | **0.0101** | 0.0582 | 58.86% | 0.44% | 0.21% | 304.9 | 0.00% | 1.43M (88%r) | done 33 |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace` 蓝本实测：中位 0.0096 / max 0.0605 /
fixed 61.26% / broken 0.46% / halluc 0.26% / spans 254.5 / key_leak 0.00% /
out 2.12M（91%r）/ done 33）。同端点同参数、只升版本，**预期差异小**：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位 / fixed 与蓝本接近（0.0096 / 61.26% 附近），臂间排序不变（find_replace 仍优于 rewrite 的中位 0.0120 一档） | 中位或 fixed 大幅偏离蓝本 ⇒ 版本升级本身改变了编辑接口层面的中心趋势 |
| 尾部形态保持蓝本量级（max ≈ 0.0605，无灾难型样本） | max 蹿到 rewrite 式灾难量级（蓝本批次 rewrite max 0.9648）⇒ v4.1 在 find_replace 上出现了 v4 没有的尾部失败 |
| `key_leak` 维持 0.00%（蓝本批次八单元全场为零） | 出现泄漏 ⇒ v4.1 对「never include them in what you output」的遵循退化 |
| 调用拒绝率与 v4 同量级（1-shot 下被拒即作废，直接压低 fixed） | 拒绝率显著变化 ⇒ 版本间遵循方言/格式的能力差异，不是接口性质 |
| 截断样本 = 0（同端点同 393216 预算，蓝本 done 33 无截断） | 出现 `incomplete`/`budget_exceeded` 异常 ⇒ 先查 v4.1 的输出长度行为是否变化 |
## 解读

跑后数据与跨版本对照汇总于批次报告 `../report/2026-09-18-doc-1shot-v41.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **编辑接口层面的结论在版本升级后是否保持** —— 蓝本批次的核心发现（接口
   差异在中心趋势上不可分、尾部差 33 倍；find_replace fixed 61.26% /
   broken 0.46% / max 0.0605）目前只是 v4-flash 的性质。同端点只升版本，
   若臂间排序、尾部形态、key_leak 等结构性质变了，那就是 **v4.1 的行为变化**，
   不能归因于接口、端点、路由或预算中的任何一项。
2. **reasoning 占比** —— volc v4 约 90%+（蓝本 out 2.12M，91%r）。v4.1 待看：
   若显著不同，则「可见输出的压缩优势被思考开销吞掉」这条结论要按模型版本
   分别陈述；同端点同预算下此差可直接归因于版本。
3. **拒绝率** —— 「不唯一/不匹配拒绝」在 1-shot 下被拒即作废。与 v4 同量级
   ⇒ 是接口的性质；差很多 ⇒ 是版本间遵循格式的能力差异。

## 资产与备注

- 报告：`runs/v41-dta19-doc-1shot-find-replace/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/volc-deepseek-v4.1-flash.toml` —— 与蓝本
  `configs/models/volc-deepseek-v4-flash.toml` 的**唯一差异是模型名**
  （`deepseek-v4-flash` → `deepseek-v4.1-flash`）：同协议 `openai-response`，
  同端点 `https://ark.cn-beijing.volces.com/api/plan/v3`，同 `context_window=1048576`
  （1024k，信息性），同 `output_length=393216`（384k，显式下发为
  `max_output_tokens`），采样参数同样留空（不下发，用端点默认）。
  除模型版本外的一切（提示词三段、视图、工具、预算、数据）与蓝本单元逐字相同。

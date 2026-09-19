# v41-dta19-doc-1shot-find-replace-blocked

> 状态：已完成（2026-09-18）

实验单元（plan/neo_experiment.md 实验2）：**doc 级、find_replace + 注意力控制、
1 doc per session、1 shot，num-key 视图** —— 与 `../dta19-doc-1shot-find-replace-blocked`
**配置逐字相同**，唯一变量是**模型版本**（`volc-deepseek-v4-flash` →
`volc-deepseek-v4.1-flash`，即模型名 `deepseek-v4-flash` → `deepseek-v4.1-flash`）。

复现序列中的位置：volc deepseek-v4-flash（蓝本）→ OpenRouter GLM 5.3 Flash →
Packy Grok 4.6 → **本批次 = 同端点模型版本升级**。与此前跨端点/跨模型复现不同，
本批次连端点都不变：同火山端点（`https://ark.cn-beijing.volces.com/api/plan/v3`）、
同协议（openai-response）、同上下文声明（1024k）、同输出预算
（`output_length=393216` = 384k，显式下发为 max_output_tokens）——是历次复现中
控制最严的一次，回答「版本升级是否改变编辑接口层面的结论」。

## Tool

- 工具集：`src/agent/numkey.py::FindReplaceBlockedToolSet`（注册键 `find_replace_blocked`）
- 配置：`configs/toolsets/find_replace_blocked.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::numkey`（`b12` → `"12"`，稳定 id）+ `src/view/defaults.py::cat_n`（`N: 内容`）；抬头经 `src/view/present.py::present_file`（`label="Text"`）

继承 `FindReplaceNumkeyToolSet`，**同一工具实现**，唯一差别是 prompt 多一段
注意力控制条款。工具语义：num-key 视图输入；`find_replace(text, "old", "new")`
在整个 path 内唯一匹配（0 或 >1 拒绝执行并回报冲突数，1-shot 下被拒即作废）；
key 只看得见、用不上。对照单元 `dta19-doc-1shot-find-replace-numkey` 之差 =
注意力控制条款的净效果。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + NUMKEY_VIEW_CLAUSE
       + FIND_REPLACE_NUMKEY_CLAUSE
       + ATTENTION_CLAUSE
       + ONE_SHOT_NOTICE_TOOLS
```

提示词组件列表：

**BLOCR instruction**：`datasets/hipe_2026/instruction.md`

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

**NUMKEY_VIEW_CLAUSE**（四臂共享的 view description）：`src/agent/numkey.py`

```txt
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output.
```

**FIND_REPLACE_NUMKEY_CLAUSE**：`src/agent/numkey.py`（由
`src/agent/standard.py::FIND_REPLACE_ANTHROPIC_CLAUSE` 单源 `.replace` 派生，
差异仅 read 一行多 `with its num-keys`）

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
- find_replace(path, "old", "new") — replace "old" with "new" in `path`. "old" must be copied VERBATIM from the text and must match EXACTLY ONE place in `path`. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```

**ATTENTION_CLAUSE**（本单元与 `patch_find_replace` 独有的实验变量）：
`src/agent/numkey.py`

```txt
Work in two passes before you emit any call.

Pass 1 — one block at a time. Go through the blocks in order and note what looks wrong inside each block on its own. Do not decide on any fix yet.

Pass 2 — across blocks. Now read the whole text. The same word, name or spelling usually appears more than once: where one occurrence is clean, it tells you how a garbled one elsewhere should read. Settle the notes from pass 1 with that evidence, and drop any you can no longer justify.

Then emit your calls.
```

**ONE_SHOT_NOTICE_TOOLS**（全部 neo 臂共有，永远在最后）：`src/agent/standard.py`

```txt
You have only ONE chance: this task gives you a single response — no feedback, no retry, no second turn.
Emit ALL your calls in this one response, with done() as the last line.
```

### 每轮对话

1-shot：只有第一轮。模型响应后不再有任何轮次——调用执行完即 extract
（未以 `done()` 收尾记 `budget_exceeded`，产出照常评分）。

第一轮：

- system: 上方装配的五段拼接（唯一一轮，无所谓 unchanged）
- user: `--- INPUT (language: de) ---` + num-key 视图 + `--- END OF INPUT ---`；
  视图 = 抬头 `--- [Text: text] ---` + 逐块 `N: 内容`（N = 稳定 num-key，
  约 300~400 块/篇），由 `present_input` 产出
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
    --toolsets noop,find_replace_blocked `
    --model volc-deepseek-v4.1-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/v41-dta19-doc-1shot-find-replace-blocked --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_blocked \
    --model volc-deepseek-v4.1-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/v41-dta19-doc-1shot-find-replace-blocked --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_blocked` | **0.0105** | 0.0308 | 60.23% | 0.36% | 0.18% | 320.2 | 0.00% | 1.46M (87%r) | done 33 |

`noop` 与模型无关，中位应约 **0.0238**、max 约 **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace-blocked` 已跑结果：volc v4 中位
**0.0109** / max **0.0659** / fixed **47.99%** / broken **0.38%** / halluc
**0.21%** / spans **224.7** / key_leak **0.00%** / out tok **2.58M（92% reasoning）**
/ done 33。版本升级预期差异小——以下任何一条结构性质变了，就是 v4.1 的行为变化）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位仍在 0.0109 附近（vs noop 0.0238 约减半的量级） | 中位贴近 noop 或大幅偏离 0.0109 ⇒ 版本升级改变了中心趋势 |
| 臂间排序保持：blocked 不优于 numkey（蓝本 numkey → blocked 中位 0.0087 → 0.0109，注意力条款净亏） | v4.1 上排序翻转 ⇒ 「注意力条款对 find_replace 是净亏」只是 v4 的性质 |
| 尾部 max 维持 0.0659 不劣化（= 没把最差样本改得更糟） | max 显著超过 0.0659 ⇒ 尾部形态随版本改变 |
| fixed/broken 比例约 47.99% / 0.38%（改动多、误伤少） | broken 占比大幅抬升 ⇒ 「整篇唯一匹配」护栏在 v4.1 上失效 |
| key_leak 仍为 0 | v4.1 泄漏 ⇒ 那条契约是模型版本特性不是提示词效果 |
| out tok 量级 2.58M、reasoning 占比约 92% | 占比显著不同 ⇒ 「两遍思考的开销」结论要按版本分别陈述 |
## 解读

跑后数据与跨版本对照汇总于批次报告 `../report/2026-09-18-doc-1shot-v41.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **注意力条款的净效果在版本升级后是否同向同量级** —— volc v4 上 blocked vs
   numkey：fixed 51.00% → 47.99%、broken 0.39% → 0.38%、spans 218.2 → 224.7，
   中位 0.0087 → 0.0109（注意力条款反而略抬高）。v4.1 上同一对照
   （待跑的 `v41` numkey 单元）是否复现这个方向与量级；若排序翻转，
   「注意力条款对 find_replace 是净亏」就只是 v4 的性质。
2. **reasoning 占比与输出膨胀** —— volc v4 是 92%（numkey 臂 90%），注意力条款
   带来 2.13M → 2.58M 的输出增量。v4.1 待看；若显著不同，则「注意力条款的成本
   主要花在思考上」这条结论要按版本分别陈述。
3. **拒绝率** —— 「整篇唯一匹配」（0 或 >1 拒绝）在 1-shot 下被拒即作废。
   拒绝规模与 v4 同量级 ⇒ 是接口的性质；差很多 ⇒ 是版本间遵循格式/挑选
   唯一上下文的能力差异。

## 资产与备注

- 报告：`runs/v41-dta19-doc-1shot-find-replace-blocked/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/volc-deepseek-v4.1-flash.toml` —— 与
  `configs/models/volc-deepseek-v4-flash.toml` 的**唯一差异 = 模型名**
  （`deepseek-v4-flash` → `deepseek-v4.1-flash`）；同火山端点
  `https://ark.cn-beijing.volces.com/api/plan/v3`，协议 openai-response，
  `context_window = 1048576`（1024k，信息性），`output_length = 393216`
  （384k，显式下发为 max_output_tokens）。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4.1-flash.toml`
  未漂移。

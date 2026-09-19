# mm3-dta19-doc-1shot-find-replace-blocked

> 状态：已完成（2026-09-19）

实验单元（plan/neo_experiment.md 实验2）：**doc 级、find_replace + 注意力控制、
1 doc per session、1 shot，num-key 视图** —— 与 `../dta19-doc-1shot-find-replace-blocked`
**配置逐字相同**，唯一变量是**模型**（`deepseek-v4-flash` → `MiniMax-M3[1m]`，
配置键 `minimax-m3-1m`）。

跨模型复现序列中的位置：volc deepseek-v4-flash（蓝本）→ Openrouter GLM 5.3 Flash
（`../Openrouter-GLM-5_3/`）→ Packy Grok 4.6（`../Packy-Grok-4_6/`）→
volc deepseek-v4.1-flash（`../Volc-DSv4_1/`）→ **本批次 = 新厂商新模型 +
新端点 + 新协议**。本批次走 MiniMax 官方 Anthropic 兼容端点
（`https://api.minimax.cn/anthropic`），模型 `MiniMax-M3[1m]`——是复现序列中
**第一个 anthropic 协议批次**（此前全部为 openai-completion / openai-response）。
两个由此而来的口径差异：(a) system 提示词经顶层 `system` 字段下发，而非
messages 首条；(b) Anthropic 口径不单列 reasoning token——usage 里 reasoning
含在 output_tokens 内（`reasoning_tokens=None`），与 volc / OpenRouter 批次
「out tok (xx%r)」直接比 reasoning 占比不可行，只能比总 output token。
声明性预算与上一批逐字对齐：`context_window=1048576`（1024k，信息性）、
`output_length=393216`（384k，anthropic 协议强制下发为 max_tokens）；
采样参数留空 = 不下发。与上一批「连端点都不变」相反，本批次**端点与协议是
未控制变量**：显著偏离先归端点/协议，再归模型。要回答的问题仍是
「编辑接口层面的结论是否跨模型稳健」。

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
    --model minimax-m3-1m `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/mm3-dta19-doc-1shot-find-replace-blocked --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_blocked \
    --model minimax-m3-1m \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/mm3-dta19-doc-1shot-find-replace-blocked --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_blocked` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 335k | budget_exceeded 29, done 4 |

`noop` 与模型无关，中位应约 **0.0238**、max 约 **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace-blocked` 已跑结果：volc v4 中位
**0.0109** / max **0.0659** / fixed **47.99%** / broken **0.38%** / halluc
**0.21%** / spans **224.7** / key_leak **0.00%** / out tok **2.58M（92% reasoning）**
/ done 33；第二参照 `../Volc-DSv4_1/` 实测：中位 **0.0105** / max **0.0308** /
fixed **60.23%** / broken **0.36%** / halluc **0.18%** / spans **320.2** /
key_leak **0.00%** / out tok **1.46M（87%r）** / done 33。以下任何一条结构性质
变了，先归端点/协议（未控制变量），再归模型）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位仍在 0.0109 附近（vs noop 0.0238 约减半的量级） | 中位贴近 noop 或大幅偏离 0.0109 ⇒ 中心趋势变了，先归端点协议再归模型 |
| 臂间排序保持：blocked 不优于 numkey（蓝本 numkey → blocked 中位 0.0087 → 0.0109，注意力条款净亏） | 本批次排序翻转 ⇒ 「注意力条款对 find_replace 是净亏」只是 v4 / Volc-DSv4_1 的性质（先排端点/协议因素） |
| 尾部 max 维持 0.0659 不劣化（= 没把最差样本改得更糟） | max 显著超过 0.0659 ⇒ 尾部形态变了（先查端点截断行为） |
| fixed/broken 比例约 47.99% / 0.38%（改动多、误伤少） | broken 占比大幅抬升 ⇒ 「整篇唯一匹配」护栏在新模型/端点下失效（先归端点协议再归模型） |
| key_leak 仍为 0 | MiniMax-M3 泄漏 ⇒ 那条契约是模型特性不是提示词效果 |
| out tok 总量与 v4 2.58M / `../Volc-DSv4_1/` 1.46M 同量级（anthropic 口径 reasoning 含在 output_tokens 内，占比不可直接比） | 总量显著不同 ⇒ 「两遍思考的开销」结论要按口径限制分别陈述 |
## 解读

跑后数据与跨批次对照汇总于批次报告 `../report/2026-09-19-doc-1shot-mm3.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **注意力条款的净效果在换模型（+ 新端点/协议）后是否同向同量级** —— volc v4 上
   blocked vs numkey：fixed 51.00% → 47.99%、broken 0.39% → 0.38%、
   spans 218.2 → 224.7，中位 0.0087 → 0.0109（注意力条款反而略抬高）。
   本批次同一对照（同批 `mm3-dta19-doc-1shot-find-replace-numkey` 单元）是否
   复现这个方向与量级；若排序翻转，「注意力条款对 find_replace 是净亏」
   就只是既有批次的性质（端点/协议未控制，先排端点协议因素）。
2. **输出 token 总量与输出膨胀** —— volc v4 是 2.58M（92% reasoning，numkey 臂
   2.13M / 90%），注意力条款在 v4 带来 2.13M → 2.58M 的输出增量；
   `../Volc-DSv4_1/` 是 1.46M（87%r）。本批次 anthropic 口径 reasoning 含在
   output_tokens 内（`reasoning_tokens=None`），占比不可与既有批次直接比，
   只能比总 output token 及 numkey → blocked 的总量增量；若显著不同，
   「注意力条款的成本主要花在思考上」这条结论要按口径限制分别陈述。
3. **拒绝率** —— 「整篇唯一匹配」（0 或 >1 拒绝）在 1-shot 下被拒即作废。
   拒绝规模与 v4 / `../Volc-DSv4_1/` 同量级 ⇒ 是接口的性质；差很多 ⇒
   是模型遵循格式/挑选唯一上下文的能力差异。

## 资产与备注

- 报告：`runs/mm3-dta19-doc-1shot-find-replace-blocked/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/minimax-m3-1m.toml` —— MiniMax 官方 Anthropic 兼容端点
  （`https://api.minimax.cn/anthropic`），协议 `anthropic`（POST /v1/messages，
  x-api-key 鉴权），模型 `MiniMax-M3[1m]`；`context_window=1048576`
  （1024k，信息性），`output_length=393216`（384k，anthropic 协议强制下发为
  max_tokens）；采样参数留空 = 不下发，用端点默认。凭证 `MINIMAX_API_KEY`
  在项目根 `.env`。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/minimax-m3-1m.toml` 未漂移。

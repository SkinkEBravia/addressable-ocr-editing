# mm3-dta19-doc-1shot-find-replace-numkey

> 状态：已完成（2026-09-19）

实验单元（plan/neo_experiment.md 实验2）：**doc 级、find_replace、1 doc per session、
1 shot，num-key 视图** —— 与 `../dta19-doc-1shot-find-replace-numkey` **配置逐字相同**，
唯一变量是**模型**（`deepseek-v4-flash` → `MiniMax-M3[1m]`，配置
`configs/models/minimax-m3-1m.toml`）。

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

- 工具集：`src/agent/numkey.py::FindReplaceNumkeyToolSet`（注册键 `find_replace_numkey`）
- 配置：`configs/toolsets/find_replace_numkey.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::numkey`（`b12` → `"12"`，稳定 id）+ `cat_n`（`N: 内容`）；
  抬头经 `src/view/present.py::present_file`（`label="Text"`）

`find_replace(text, "old", "new")`：全 path 唯一匹配（0 或 >1 拒绝执行并回报冲突数），
工具语义与实验1 的 `find_replace_anthropic_style` **完全一致**；唯一差别是输入与
`read()` 带 num-key——key 只「看得见」、工具参数用不上它。IR-backed，编辑可跨块
（降解为 SetContent + Remove），既有块 key 不变更、不复用。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + NUMKEY_VIEW_CLAUSE
       + FIND_REPLACE_NUMKEY_CLAUSE
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

**NUMKEY_VIEW_CLAUSE**（实验2 四臂共享的 view description）：`src/agent/numkey.py`

```txt
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output.
```

**FIND_REPLACE_NUMKEY_CLAUSE**（与实验1 同臂条款逐字相同，仅 read 一行多
`with its num-keys`；由 `FIND_REPLACE_ANTHROPIC_CLAUSE` 单源 `.replace` 派生）：
`src/agent/numkey.py`

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
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

- system: 上方装配的四段拼接
- user: `--- INPUT (language: de) ---` + num-key 视图 + `--- END OF INPUT ---`；
  视图 = 抬头 `--- [Text: text] ---` + 逐块 `N: 内容`（N = 稳定 num-key），
  由 `present_input` 产出
- assistant（期望形态）：一口气给出全部调用，`done()` 收尾；
  `"old"` 逐字复制块内容（**不含 num-key 前缀**），例如

```txt
find_replace(text, "brovvn", "brown")
find_replace(text, "Thé quick", "The quick")
done()
```

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,find_replace_numkey `
    --model minimax-m3-1m `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/mm3-dta19-doc-1shot-find-replace-numkey --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_numkey \
    --model minimax-m3-1m \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/mm3-dta19-doc-1shot-find-replace-numkey --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_numkey` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 299k | budget_exceeded 29, done 4 |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace-numkey` 蓝本实测：v4 中位 0.0087 /
max 0.0659 / fixed 51.00% / broken 0.39% / halluc 0.23% / spans 218.2 /
key_leak 0.00% / 2.13M（90% reasoning）；第二参照 `../Volc-DSv4_1/` 实测：
中位 0.0097 / max 0.0479 / fixed 57.98% / broken 0.49% / halluc 0.26% /
spans 321.7 / key_leak 0.00% / 1.47M（86%r）/ done 33。若臂间排序、尾部形态、
key_leak 等结构性质变了，先归端点/协议（未控制变量），再归模型）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位与尾部与 v4 同量级（中位 ≈0.0087，max ≈0.0659 即 noop 最差样本；第二参照 0.0097 / 0.0479） | 量级漂移 ⇒ 「带标记臂 vs 不带标记臂」结论要按模型分别陈述（先排端点/协议因素） |
| 臂间排序不变（find_replace_numkey 中位远低于 noop 的 0.0238，且 max 不超过 noop 最差样本） | 排序翻转或臂尾部超过 noop ⇒ 本批次引入了既有批次没有的失败模式（先查端点/协议行为） |
| fixed / broken / halluc 与 v4 同量级（51.00% / 0.39% / 0.23%） | 显著偏移 ⇒ 任务行为变了，不是接口的性质（先归端点/协议再归模型） |
| `key_leak` 仍为 0 | MiniMax-M3 泄漏 ⇒ 「key 只看得见、不进文本」那条契约是模型特性不是提示词效果 |
| 拒绝率（含抄 num-key 进 `"old"` 触发的 `PATTERN_NOT_FOUND`）与 v4 同量级 | 差很多 ⇒ 是模型遵循格式能力的差异，不是接口的性质 |
## 解读

跑后数据与跨批次对照汇总于批次报告 `../report/2026-09-19-doc-1shot-mm3.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **臂间排序与尾部形态在换模型（+ 新端点/协议）后是否保持** —— v4 上中位
   0.0087、max 0.0659（尾部 = noop 最差样本，臂未引入新错误）、fixed 51.00% /
   broken 0.39% / halluc 0.23%；`../Volc-DSv4_1/` 同端点版本升级下同量级
   （中位 0.0097 / max 0.0479）。本批次是同提示词、同预算下的又一次跨模型
   对照，但端点/协议未控制：显著偏离先归端点协议再归模型。
2. **输出 token 总量** —— volc v4 out tok 2.13M（90% reasoning），
   `../Volc-DSv4_1/` 1.47M（86%r）。本批次 anthropic 口径不单列 reasoning
   token（含在 output_tokens 内，`reasoning_tokens=None`），占比不可与既有
   批次直接比，只能比总 output token：总量若显著不同，「可见输出的压缩优势
   被思考开销吞掉」这条结论要按口径限制重新陈述。
3. **拒绝率** —— 「0 或 >1 匹配拒绝」与「抄 num-key 进 `"old"` 的
   `PATTERN_NOT_FOUND`」的比例是否与 v4 同量级。同量级 ⇒ 是接口的性质；
   差很多 ⇒ 是模型遵循格式能力的差异。

## 资产与备注

- 报告：`runs/mm3-dta19-doc-1shot-find-replace-numkey/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 注意：模型若把 num-key 前缀抄进 `"old"` 会触发 `PATTERN_NOT_FOUND`
  （key 不在真实文本里）——1-shot 下该条直接作废，拒绝率里单列观察。
- 模型：`configs/models/minimax-m3-1m.toml` —— MiniMax 官方 Anthropic 兼容端点
  （`https://api.minimax.cn/anthropic`）、协议 `anthropic`（POST /v1/messages，
  x-api-key 鉴权）、模型 `MiniMax-M3[1m]`；`context_window=1048576`
  （1024k，信息性）、`output_length=393216`（384k，anthropic 协议强制下发为
  max_tokens，不配置则由适配器 ConfigError 拒绝）；采样参数留空（不下发，
  用端点默认）。凭证 `MINIMAX_API_KEY` 在项目根 `.env`。除模型外的一切
  （提示词四段、视图、工具、预算、数据）与蓝本单元逐字相同。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/minimax-m3-1m.toml` 未漂移。

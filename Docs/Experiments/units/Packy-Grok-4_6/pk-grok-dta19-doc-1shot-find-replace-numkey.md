# pk-grok-dta19-doc-1shot-find-replace-numkey

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2）：**doc 级、find_replace、1 doc per session、
1 shot，num-key 视图** —— 与 `../dta19-doc-1shot-find-replace-numkey` **配置逐字相同**，
唯一变量是**模型**（`volc-deepseek-v4-flash` → `packy-grok-4.6`）。

跨模型复现序列的第三个模型（volc-deepseek 蓝本 → Openrouter GLM → 本批次 Grok 4.6）；
与 `../Openrouter-GLM-5_3/` 批次互为模型对照——同任务同配置、不同模型。

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
    --model packy-grok-4.6 `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/pk-grok-dta19-doc-1shot-find-replace-numkey --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_numkey \
    --model packy-grok-4.6 \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/pk-grok-dta19-doc-1shot-find-replace-numkey --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `find_replace_numkey` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与 volc 单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace-numkey`：volc 中位 0.0087 / max 0.0659 /
fixed 51.00% / broken 0.39% / halluc 0.23% / spans 218.2 / 2.13M（90% reasoning））：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位与尾部与 volc 同量级（中位 ≈0.0087，max ≈0.0659 即 noop 最差样本） | 量级漂移 ⇒ 「带标记臂 vs 不带标记臂」结论要按模型分别陈述 |
| `key_leak` 仍为 0 | Grok 泄漏 ⇒ 「key 只看得见、不进文本」那条契约是模型特性不是提示词效果 |
| 拒绝率（含抄 num-key 进 `"old"` 触发的 `PATTERN_NOT_FOUND`）与 volc 同量级 | 差很多 ⇒ 是模型遵循格式的能力差异，不是接口的性质 |

## 解读

<跑完填。对照 ../dta19-doc-1shot-find-replace-numkey：唯一变量 = 模型。>

要回答的三件事：

1. **中位与尾部的形态在换模型后是否保持** —— volc 上中位 0.0087、max 0.0659
   （尾部 = noop 最差样本，臂未引入新错误）、fixed 51.00% / broken 0.39% /
   halluc 0.23%。这些只在单模型上验证过。
2. **reasoning 占比** —— volc 约 90%（out tok 2.13M）；GLM 实测可见输出比
   deepseek 啰嗦 6 倍。Grok 待看。若显著不同，则「可见输出的压缩优势被思考
   开销吞掉」这条结论要按模型分别陈述。
3. **拒绝率** —— 「0 或 >1 匹配拒绝」与「抄 num-key 进 `"old"` 的
   `PATTERN_NOT_FOUND`」的比例是否与 volc 同量级。同量级 ⇒ 是接口的性质；
   差很多 ⇒ 是模型遵循格式的能力差异。

## 资产与备注

- 报告：`runs/pk-grok-dta19-doc-1shot-find-replace-numkey/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 注意：模型若把 num-key 前缀抄进 `"old"` 会触发 `PATTERN_NOT_FOUND`
  （key 不在真实文本里）——1-shot 下该条直接作废，拒绝率里单列观察。
- 模型：`configs/models/packy-grok-4.6.toml` —— Packy 中转端点
  `https://cf.api.fan/v1`、协议 openai-response（该模型不支持 chat/completions，
  实测 protocol_not_supported）、模型 `grok-4.6`，`output_length=393216`
  （与 volc 各单元逐字对齐）、`max_transport_retries=8`（中转稳定性未知，
  与 OpenRouter 批次同深度）。除模型外的一切（提示词四段、视图、工具、预算、
  数据）与 volc 单元逐字相同。
- 中转注入已验证无泄漏：该中转在不带 instructions 的请求里会注入一段默认
  Codex CLI 系统提示词；本单元每条请求都自带 instructions（五段 system 拼接），
  实测注入被整体替换、无泄漏（input_tokens 从 4632 回落到正常量级）。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/packy-grok-4.6.toml` 未漂移。

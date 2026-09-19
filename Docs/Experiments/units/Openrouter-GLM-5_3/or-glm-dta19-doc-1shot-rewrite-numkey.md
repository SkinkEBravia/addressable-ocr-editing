# or-glm-dta19-doc-1shot-rewrite-numkey

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2）：**doc 级、rewrite、1 doc per session、
1 shot，num-key 视图** —— 与 `../dta19-doc-1shot-rewrite-numkey` **配置逐字相同**，
唯一变量是**模型**（`volc-deepseek-v4-flash` → `openrouter-glm-5.3-flash`）。
本单元是「key 泄漏」的主要观测点在第二个模型上的复现。

与 `../glm-5.3-flash/` 批次的关系：同模型（GLM 5.3 Flash）但不同端点——
本单元走 OpenRouter（provider 锁定 `modal/fp8`），glm-5.3-flash 批次走火山引擎。
且本批次 `output_length = 393216`，与 volc dta19 各单元逐字对齐，
**不存在** glm-5.3-flash 批次 131072（128k）的输出预算混淆项。

## Tool

- 工具集：`src/agent/numkey.py::RewriteNumkeyToolSet`（注册键 `rewrite_numkey`）
- 配置：`configs/toolsets/rewrite_numkey.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::numkey`（`b12` → `"12"`，稳定 id）+ `cat_n`（`N: 内容`）；
  抬头经 `src/view/present.py::present_file`（`label="Text"`）

空工具集：单轮整篇重写，extract 从末轮 assistant 文本解析 JSON 字段。
与 `rewrite_anthropic_style` 的唯一差别 = 输入是 num-key 视图（IR-backed：
partition_lines + birth，key = BlockKey 序号）；产出要求不带 key 的纯文本。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + NUMKEY_VIEW_CLAUSE
       + REWRITE_CLAUSE
       + ONE_SHOT_NOTICE_REWRITE
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

**REWRITE_CLAUSE**（输出条款，与旧 `rewrite` 系共享同一常量）：`src/agent/standard.py`

```txt
Return a JSON object with exactly one field: "ocr_postcorrection_output".
Return ONLY valid JSON. No explanation, no preamble, no markdown fences.

After the JSON object, output a CSV corrections log.
Marker line: CORRECTIONS_CSV
Columns: document_id,ocr_hypothesis_snippet,ocr_postcorrection_snippet,error_type,confidence,notes
- error_type: over_segmentation, misrecognized_char, under_segmentation, missing_character, wrong_word, uncertain, no_change, or custom:label
- confidence: high, medium, or low
- One row per document_id (use no_change if unchanged)
- Do not wrap the CSV in markdown fences
```

**ONE_SHOT_NOTICE_REWRITE**（全部 neo 臂共有，永远在最后）：`src/agent/standard.py`

```txt
You have only ONE chance: this task gives you a single response — no feedback, no retry, no second turn.
Emit the complete output in this one response.
```

### 每轮对话

1-shot：只有第一轮。任何非空响应即收束（空工具集，`parse` 恒为 Done）。

第一轮：

- system: 上方装配的四段拼接
- user: `--- INPUT (language: de) ---` + num-key 视图 + `--- END OF INPUT ---`；
  视图 = 抬头 `--- [Text: text] ---` + 逐块 `N: 内容`（N = 稳定 num-key，
  约 300~400 块/篇），由 `present_input` 产出
- assistant（期望形态）：一个 JSON 对象 + 尾部 CSV 日志（同无 key 的 rewrite 单元；
  `ocr_postcorrection_output` 内**不得出现 num-key**）

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite_numkey `
    --model openrouter-glm-5.3-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/or-glm-dta19-doc-1shot-rewrite-numkey --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_numkey \
    --model openrouter-glm-5.3-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/or-glm-dta19-doc-1shot-rewrite-numkey --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `rewrite_numkey` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与 volc 单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-rewrite-numkey`：volc 中位 0.0110 / max 0.0322 /
fixed 69.72% / broken 0.82% / halluc 0.48% / spans 377.6 / key_leak 0.00% /
out tok 2.59M，reasoning 占 92%）：

| 预期 | 什么结果算预期落空 |
|---|---|
| `key_leak` 读数仍为 0（volc 上原预期「此臂最易泄漏」已落空，实测 0.00%） | GLM 泄漏 ⇒ 「不抄 key」的契约遵守是模型特性，不是提示词效果 |
| cmer 中位与尾部与 volc 同量级（0.0110 / 0.0322） | 量级漂移 ⇒ num-key 视图对 rewrite 交付的影响是模型相关的 |
| fixed / broken / halluc 与 volc 同量级（69.72% / 0.82% / 0.48%） | 显著变差 ⇒ 「回抄全文」的交付能力在该接口下按模型分档 |
| 截断样本 = 0/33（output_length 与 volc 对齐，无预算混淆项） | 出现 `incomplete` ⇒ 先查 OpenRouter 端点行为再看质量数字 |

`key_leak` 单列，不进 broken。

## 解读

<跑完填。对照 ../dta19-doc-1shot-rewrite-numkey：唯一变量 = 模型。>

要回答的三件事：

1. **key_leak 是否仍为 0** —— volc 上本臂实测 0.00%，与跑前预期
   （「回抄全文又要忍住不抄 key」最易泄漏）相反。GLM 若同样为 0，
   则「不把 num-key 抄进产出」是提示词契约的稳健效果；若泄漏，
   则它是 volc 的模型特性。
2. **中位与尾部** —— volc 中位 0.0110 / max 0.0322。num-key 出现在输入里
   对 rewrite 交付方式的影响（对照无 key 的 rewrite 单元）是否在换模型后
   保持同方向、同量级。
3. **reasoning 占比与交付质量** —— volc 是 92%、fixed 69.72%、broken 0.82%、
   halluc 0.48%。若 GLM 的 reasoning 占比显著不同，「可见输出的压缩优势
   被思考开销吞掉」这条结论要按模型分别陈述；若 broken/halluc 量级漂移，
   则「整篇回抄」的可靠性是模型分档的。

## 资产与备注

- 报告：`runs/or-glm-dta19-doc-1shot-rewrite-numkey/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- `key_leak` 是启发式指示器：历史报纸文本偶发合法 `数字: ` 行首，读数时留意。
- 模型：`configs/models/openrouter-glm-5.3-flash.toml` —— OpenRouter 端点，
  协议 `openai-response`，模型 `z-ai/glm-5.3-flash`；provider 路由经
  `extra_body` 锁定 `modal/fp8`（不允许回退，避免混量化变体与计费口径）；
  `output_length = 393216`，与 volc dta19 各单元逐字对齐。
  除模型外的一切（提示词四段、视图、工具、预算、数据）与 volc 单元逐字相同。
- OpenRouter 共享池上游限流（429）较频繁：配置已把 `max_transport_retries`
  加深到 8；仍出现 failed cell 时可经 resume 重试，不影响已完成 cell。

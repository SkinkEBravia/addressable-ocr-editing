# or-glm-dta19-doc-1shot-rewrite

> 状态：待跑

实验单元（plan/neo_experiment.md 实验1）：**doc 级、rewrite、1 doc per session、1 shot** ——
与 `../dta19-doc-1shot-rewrite` **配置逐字相同**，唯一变量是**模型**
（`volc-deepseek-v4-flash` → `openrouter-glm-5.3-flash`）。

与 `../glm-5.3-flash/` 批次的关系：**同模型（GLM 5.3 Flash）但不同端点** —— 本批次走
OpenRouter，glm-5.3-flash 批次走火山引擎。**本单元 provider 路由锁 `parasail/fp8`**；
批次内 provider 按单元分配（modal / coreweave / parasail 三家，绕开共享池限流），
故批次内跨单元对照时 provider 是未控制变量，解读须注明。且本批次
`output_length = 393216` 与 volc 各单元逐字对齐，**不存在** glm-5.3-flash 批次
`output_length = 131072` 那个已知的输出预算混淆项；跨单元对照中的唯一变量干净地只剩模型本身。

## Tool

- 工具集：`src/agent/standard.py::RewriteAnthropicToolSet`（注册键 `rewrite_anthropic_style`）
- 配置：`configs/toolsets/rewrite_anthropic_style.toml`（`max_turns=1`）
- 视图组件：`src/view/present.py::file_header`（`--- [Text: text] ---` 抬头）+ 纯原文

空工具集：单轮整篇重写，fold 状态即对话本身，extract 从末轮 assistant 文本解析
JSON 字段（失败剥 markdown 围栏，再失败用原文）。与旧 `rewrite` 臂的唯一差别 =
输入多一个 path 抬头；prompt 末尾多 1-shot 告知。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
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

**REWRITE_CLAUSE**（输出条款，与旧 `rewrite` / `rewrite_local_seq` 共享同一常量）：
`src/agent/standard.py`

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

- system: 上方装配的三段拼接
- user: `--- INPUT (language: de) ---` + `--- [Text: text] ---` + 纯原文
  + `--- END OF INPUT ---`，由 `present_input` 产出
- assistant（期望形态）：一个 JSON 对象 + 尾部 CSV 日志，例如

```txt
{"ocr_postcorrection_output": "The quick brown fox jumps\nover the lazy dog"}
CORRECTIONS_CSV
document_id,ocr_hypothesis_snippet,ocr_postcorrection_snippet,error_type,confidence,notes
...
```

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite_anthropic_style `
    --model openrouter-glm-5.3-flash-parasail `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/or-glm-dta19-doc-1shot-rewrite --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_anthropic_style \
    --model openrouter-glm-5.3-flash-parasail \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/or-glm-dta19-doc-1shot-rewrite --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `rewrite_anthropic_style` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与 volc 单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-rewrite` 的实际结果：volc 中位 **0.0120** /
max **0.9648** / fixed **67.42%** / broken **3.86%** / halluc **0.51%** /
spans **343.8** / key_leak **0.00%** / out tok **1.88M（93%r）** / done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| rewrite 臂的高 broken、高尾部在换模型后仍成立（volc：broken 3.86%、max 0.9648） | GLM 的 broken 掉到 find-replace 类臂量级（volc pfr 为 0.52%）或尾部收敛 |
| 破坏以漏抄（broken_del）为主这一形态不变 | 破坏结构换成 halluc 或截断主导 |
| `key_leak` 恒为 0（输入无 num-key，volc 实测 0.00%） | 任何非零值 ⇒ 先查视图/装载漂移 |
| 噪声越高越容易输出截断（`incomplete`）的梯度仍在 | 大面积 `incomplete` 与噪声档脱钩 ⇒ 先查端点/限流，再谈比较 |

## 解读

<跑完填。对照 `../dta19-doc-1shot-rewrite`：唯一变量 = 模型。>

要回答的三件事：

1. **rewrite 臂的「fixed 不低、尾部失控」在换模型后是否保持** —— volc 上
   中位 0.0120 但 max 冲到 0.9648、broken 3.86%（远高于 find-replace 类臂的 0.52%），
   「整篇重写的破坏以漏抄为主、尾部随噪声放大」这条结论只在单模型上验证过。
2. **reasoning 占比** —— volc 是 93%（out tok 1.88M）。若 GLM 显著不同，
   「rewrite 的输出预算大头花在思考上」这条结论要按模型分别陈述。
3. **截断与噪声的耦合** —— volc 上噪声越高越容易 `incomplete`。本单元
   output_length 与 volc 对齐（393216），若 GLM 在同样预算下截断分布不同，
   差异应归因于模型的输出长度行为而非预算配置。

## 资产与备注

- 报告：`runs/or-glm-dta19-doc-1shot-rewrite/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/openrouter-glm-5.3-flash-parasail.toml` —— OpenRouter 端点、
  协议 `openai-response`、模型 `z-ai/glm-5.3-flash`，provider 路由经 extra_body
  锁定 `parasail/fp8`（不允许回退到别家量化变体），`output_length = 393216`
  与 volc 各单元逐字对齐，`max_transport_retries = 8`。除模型外的一切
  （提示词三段、视图、工具、预算、数据）与 volc 单元逐字相同。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/openrouter-glm-5.3-flash-parasail.toml` 未漂移。
- OpenRouter 共享池上游限流（429）较频繁，配置已把 `max_transport_retries` 加深到 8；
  仍出现的 failed cell 可经 resume 重试补齐，不必整单元重跑。

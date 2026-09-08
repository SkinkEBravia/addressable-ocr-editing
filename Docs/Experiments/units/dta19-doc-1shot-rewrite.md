# dta19-doc-1shot-rewrite

> 状态：待跑

实验单元（plan/neo_experiment.md 实验1）：**doc 级、rewrite、1 doc per session、1 shot**。
对照单元：`dta19-doc-1shot-find-replace`（同一输入，唯一变量 = 交付方式）。

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
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/dta19-doc-1shot-rewrite --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_anthropic_style \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/dta19-doc-1shot-rewrite --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `rewrite_anthropic_style` | **0.0120** | 0.9648 | 67.42% | 3.86% | 0.51% | 343.8 | 0.00% | 1.88M (93%r) | done 33 |

预期：与 find_replace 单元相比 fixed 相近、broken 更高；破坏以漏抄（broken_del）
为主；噪声越高越容易输出截断（`incomplete`）。`key_leak` 应恒为 0（输入无 num-key）。

## 解读

<跑完填。与 `dta19-doc-1shot-find-replace` 逐档对账 plan 实验1 的预期表；
旧臂参照 runs/dta19-doc-1t 的 rewrite（纯原文但无 path 抬头，口径差异需注明）。>

## 资产与备注

- 报告：`runs/dta19-doc-1shot-rewrite/report.json`；磁带：`runs/dta19-doc-1shot-rewrite/sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4-flash.toml` 未漂移。

# dta19-doc-1shot-find-replace

> 状态：待跑

实验单元（plan/neo_experiment.md 实验1）：**doc 级、find_replace、1 doc per session、1 shot**。
对照单元：`dta19-doc-1shot-rewrite`（同一输入，唯一变量 = 交付方式）。

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
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/dta19-doc-1shot-find-replace --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_anthropic_style \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/dta19-doc-1shot-find-replace --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_anthropic_style` | **0.0096** | 0.0605 | 61.26% | 0.46% | 0.26% | 254.5 | 0.00% | 2.12M (91%r) | done 33 |

预期：与 rewrite 单元 fixed 相近，差别集中在 broken（预期更低、以改错
broken_sub 为主）。另数**调用拒绝率**（不唯一/不匹配，1-shot 下被拒即作废）。

## 解读

<跑完填。与 `dta19-doc-1shot-rewrite` 逐档对账 plan 实验1 的预期表；
与 `dta19-doc-1shot-find-replace-numkey` 的差 = 「key 光是看得见」的净效果（关键对照）。>

## 资产与备注

- 报告：`runs/dta19-doc-1shot-find-replace/report.json`；磁带：`runs/dta19-doc-1shot-find-replace/sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 旧臂参照：runs/dta19-doc-1t 的 `find_replace` 是 replace-all 语义且无 path 抬头，对照时注明。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4-flash.toml` 未漂移。

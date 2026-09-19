# pk-grok-dta19-doc-1shot-find-replace

> 状态：待跑

实验单元：**doc 级、find_replace、1 doc per session、1 shot** —— 与
`../dta19-doc-1shot-find-replace` **配置逐字相同**，唯一变量是**模型**
（`volc-deepseek-v4-flash` → `packy-grok-4.6`）。

跨模型复现序列的第三个模型（volc-deepseek 蓝本 → `../Openrouter-GLM-5_3/`
→ 本批次）：与 `../Openrouter-GLM-5_3/` 批次互为模型对照——同任务同配置、
不同模型，批次意在回答「结论跨模型是否成立」。

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
    --model packy-grok-4.6 `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/pk-grok-dta19-doc-1shot-find-replace --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_anthropic_style \
    --model packy-grok-4.6 \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/pk-grok-dta19-doc-1shot-find-replace --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `find_replace_anthropic_style` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace`：volc 中位 0.0096 / max 0.0605 /
fixed 61.26% / broken 0.46% / halluc 0.26% / spans 254.5 / key_leak 0.00% /
out 2.12M（91%r）/ done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 「fixed 与 rewrite 相近、broken 更低（以改错 broken_sub 为主）」在换模型后仍成立 | fixed 大幅偏离 61.26%，或 broken 反超 rewrite 臂 |
| 调用拒绝率与 volc 同量级（1-shot 下被拒即作废，直接压低 fixed） | 拒绝率显著更高 ⇒ 是模型遵循方言的能力差异，不是接口性质 |
| 截断样本 ≈ 0（output_length 已与 volc 对齐 393216，无预算混淆项） | 出现 `incomplete` ⇒ 先查 Packy 中转/上游是否中途截断或限流降级 |

## 解读

<跑完填。对照 ../dta19-doc-1shot-find-replace：唯一变量 = 模型。>

要回答的三件事：

1. **fixed / broken 的形态在换模型后是否保持** —— 蓝本上 find_replace 做到
   fixed 61.26%、broken 0.46%，「fixed 与 rewrite 相近、broken 更低」这条
   此前只在 volc 一个模型上验证过（GLM 批次是第二个数据点，本批次是第三个）。
2. **reasoning 占比** —— volc 是 91%（out 2.12M）；GLM 实测可见输出比
   deepseek 啰嗦约 6 倍。Grok 待看；若又显著不同，则「可见输出的压缩优势
   被思考开销吞掉」这条结论要按模型分别陈述。
3. **拒绝率** —— 「不唯一/不匹配拒绝」在 1-shot 下被拒即作废。与 volc
   同量级 ⇒ 是接口的性质；差很多 ⇒ 是模型遵循格式的能力差异。

## 资产与备注

- 报告：`runs/pk-grok-dta19-doc-1shot-find-replace/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/packy-grok-4.6.toml` —— Packy 中转端点
  `https://cf.api.fan/v1`，协议 `openai-response`（该模型不支持
  chat/completions，实测 `protocol_not_supported`），模型 `grok-4.6`；
  `output_length=393216`（384k，与 volc dta19 各单元逐字对齐）；
  `max_transport_retries=8`（中转稳定性未知，与 OpenRouter 批次同深度）。
  除模型外的一切（提示词装配、视图、工具、预算、数据）与蓝本单元逐字相同。
- 中转注入实测：Packy 在不带 instructions 的请求里会注入一段默认 Codex CLI
  系统提示词；本单元每条请求都自带 instructions（五段 system 拼接），实测
  注入被整体替换、无泄漏（input_tokens 从 4632 回落到正常量级）。

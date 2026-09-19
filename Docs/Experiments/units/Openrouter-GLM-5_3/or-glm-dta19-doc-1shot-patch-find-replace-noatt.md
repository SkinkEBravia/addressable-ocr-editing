# or-glm-dta19-doc-1shot-patch-find-replace-noatt

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2 追加臂）：**doc 级、patch_find_replace 无注意力
条款版（num-key 定位）、1 doc per session、1 shot，num-key 视图** —— 与
`../dta19-doc-1shot-patch-find-replace-noatt` **配置逐字相同**，唯一变量是**模型**
（`volc-deepseek-v4-flash` → `openrouter-glm-5.3-flash`）。

与 `../glm-5.3-flash/` 批次的关系：同模型（GLM 5.3 Flash）但**不同端点**——
本批次走 OpenRouter、本单元 provider 路由锁定 `coreweave/fp8`；glm-5.3-flash 批次走火山引擎端点。
注意批次内 provider 是按单元分配的（modal / coreweave / parasail 三家，为绕开共享池限流），
跨单元对照时 provider 是未控制变量，解读时需注明。
且本批次 `output_length = 393216`（384k）与 volc 各单元对齐，**不存在**
glm-5.3-flash 批次 `output_length = 131072`（128k）那个已知的输出预算混淆项。

## Tool

- 工具集：`src/agent/numkey.py::PatchFindReplaceNoattToolSet`（注册键 `patch_find_replace_noatt`）
- 配置：`configs/toolsets/patch_find_replace_noatt.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::numkey`（`b12` → `"12"`，稳定 id）+ `cat_n`（`N: 内容`）；
  抬头经 `src/view/present.py::present_file`（`label="Text"`）

继承 `PatchFindReplaceToolSet`，仅覆写 `prompt_clause`（去掉 ATTENTION_CLAUSE）。
工具语义与 `patch_find_replace` 完全相同：`find_replace(text, key, "old", "new")`
唯一性只在 key 指定块内判定，未知 key 拒绝，编辑后回显被改块（key 不变）；
方言只认 `read` / `find_replace` / `done`，清单外操作 parse 层 ToolParseError。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + NUMKEY_VIEW_CLAUSE
       + PATCH_FIND_REPLACE_CLAUSE
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

**NUMKEY_VIEW_CLAUSE**（实验2 各臂共享的 view description）：`src/agent/numkey.py`

```txt
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output.
```

**PATCH_FIND_REPLACE_CLAUSE**（key 定位版 find_replace 条款）：`src/agent/numkey.py`

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
- find_replace(path, key, "old", "new") — replace "old" with "new" inside the block with num-key `key` in `path`. "old" must be copied VERBATIM from that block and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the block, then try again.
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

- system: 上方装配的四段拼接（无 ATTENTION_CLAUSE）
- user: `--- INPUT (language: de) ---` + num-key 视图 + `--- END OF INPUT ---`；
  视图 = 抬头 `--- [Text: text] ---` + 逐块 `N: 内容`（N = 稳定 num-key），
  由 `present_input` 产出
- assistant（期望形态）：一口气给出全部调用，每条带目标块的 num-key，
  `done()` 收尾，例如

```txt
find_replace(text, 1, "brovvn", "brown")
find_replace(text, 2, "Thé quick", "The quick")
done()
```

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,patch_find_replace_noatt `
    --model openrouter-glm-5.3-flash-coreweave `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/or-glm-dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace_noatt \
    --model openrouter-glm-5.3-flash-coreweave \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/or-glm-dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `patch_find_replace_noatt` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与 volc 单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-patch-find-replace-noatt`：volc 中位 0.0089 /
max 0.0621 / fixed 63.72% / broken 0.47% / halluc 0.28% / spans 317.7 /
2.11M out tok（89% reasoning）/ done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 「中心趋势不可分、尾部分得开」在换模型后仍成立 | 两个模型的尾部排序反过来 |
| `key_leak` 仍为 0 | GLM 泄漏 ⇒ 那条契约是模型特性不是提示词效果 |
| 截断样本 ≈ 0（预算 384k 与 volc 对齐，无混淆项） | 大面积 `incomplete` ⇒ 本单元不可与 volc 直接比 |

## 解读

<跑完填。对照 ../dta19-doc-1shot-patch-find-replace-noatt：唯一变量 = 模型。>

要回答的三件事：

1. **中位与尾部的排序在换模型后是否保持** —— 上一轮 noatt 臂的结论
   （volc 中位 0.0089 / max 0.0621，去掉注意力条款后尾部显著拉宽、
   max 是带注意力版 0.0295 的两倍多）只在一个模型上验证过。
2. **reasoning 占比** —— volc 本臂是 89%（2.11M out tok 中 89% 为 reasoning）。
   若 GLM 显著不同，则「可见输出的压缩优势被思考开销吞掉」这条结论要按模型分别陈述。
3. **拒绝率** —— 「多匹配拒绝」与「未知 key」的比例是否与 volc 同量级。
   同量级 ⇒ 是接口的性质；差很多 ⇒ 是模型遵循格式的能力差异。

## 资产与备注

- 报告：`runs/or-glm-dta19-doc-1shot-patch-find-replace-noatt/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/openrouter-glm-5.3-flash-coreweave.toml` —— OpenRouter 端点，
  协议 `openai-response`，模型 `z-ai/glm-5.3-flash`，provider 路由经 extra_body
  锁定 `coreweave/fp8`（不允许回退到别家，避免混量化变体与计费口径），
  `output_length = 393216`（与 volc 各单元预算对齐），`max_transport_retries = 8`。
  除模型外的一切（提示词四段、视图、工具、预算、数据）与 volc 单元逐字相同。
- OpenRouter 共享池上游限流（429）较频繁，配置已把 `max_transport_retries`
  加深到 8；failed cell 可经 resume 重试补齐。

# dta19-doc-1shot-patch-find-replace-noatt

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2 追加臂）：**doc 级、patch_find_replace 无注意力
条款版（num-key 定位）、1 doc per session、1 shot，num-key 视图**。与
`patch_find_replace` 逐字节同一实现，唯一变量 = 系统提示词去掉 ATTENTION_CLAUSE；
与 `find_replace_numkey` / `patch_find_replace` 配对成「注意力控制 × 用 key 定位」
的 2×2 对照矩阵的第四格。

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
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace_noatt \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `patch_find_replace_noatt` | **0.0089** | 0.0621 | 63.72% | 0.47% | 0.28% | 317.7 | 0.00% | 2.11M (89%r) | done 33 |

预期：与 `patch_find_replace` 的差全部归因于注意力条款缺失（two-pass 自检不再被要求）；
与 `find_replace_numkey` 的差全部归因于「用 key 定位 + 唯一性收窄到块内」。
两两对照闭合 2×2。

## 解读

<跑完填。对照 `dta19-doc-1shot-patch-find-replace`（唯一变量 = ATTENTION_CLAUSE）
与 `dta19-doc-1shot-find-replace-numkey`（唯一变量 = key 定位）。>

## 资产与备注

- 报告：`runs/dta19-doc-1shot-patch-find-replace-noatt/report.json`；磁带：`runs/dta19-doc-1shot-patch-find-replace-noatt/sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4-flash.toml` 未漂移。

# dta19-doc-1shot-patch-find-replace-unstable

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2 追加臂）：**doc 级、patch_find_replace 位置性
key 版（真行号、编辑后重排）、1 doc per session、1 shot**。外观与
`patch_find_replace` 完全相同（`N: 内容` 视图、同一 `find_replace(path, key, old, new)`
签名、同一 ATTENTION_CLAUSE），**唯一变量 = key 的稳定性**：本臂 key 是真正的行号，
每次编辑后全文重新 partition + re-birth，编号按位置重排——行数变化的编辑使同批
后续调用的 key 指错（1-shot 无回馈，指错即拒绝或改错行，正是本臂要量化的咬人点）。

## Tool

- 工具集：`src/agent/numkey.py::PatchFindReplaceUnstableToolSet`（注册键 `patch_find_replace_unstable`）
- 配置：`configs/toolsets/patch_find_replace_unstable.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::line_number`（位置性行号）+ `cat_n`（`N: 内容`）；
  抬头经 `src/view/present.py::present_file`（`label="Text"`）

继承 `PatchFindReplaceToolSet`，覆写三处：`_STRATEGY = view_mod.line_number`、
`_KEY_NOUN = "line"`（报错措辞 "no line numbered {key}"）、`_after_edit` 钩子
（编辑后全文重新 partition + re-birth，编号按位置重排）。唯一性判定、拒绝行为、
方言清单（`read` / `find_replace` / `done`，清单外 parse 层 ToolParseError）
与 `patch_find_replace` 一致。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + LINE_NUMBER_VIEW_CLAUSE
       + PATCH_FIND_REPLACE_LINES_CLAUSE
       + ATTENTION_CLAUSE
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

**LINE_NUMBER_VIEW_CLAUSE**（位置性行号的 view description，如实披露漂移语义）：
`src/agent/numkey.py`

```txt
Each line of the text is prefixed by a line number:

  <line number>: <line content>

Line numbers are POSITIONAL, not stable identifiers: whenever one of your edits adds or removes lines, the lines below it are renumbered. A number you saw before such an edit may point to a DIFFERENT line after it — within your batch of calls, later calls see the numbering shifted by your earlier edits. The numbers are not part of the text; never include them in what you output.
```

**PATCH_FIND_REPLACE_LINES_CLAUSE**（行号措辞版 find_replace 条款，
含 "CURRENT numbering shifts" 披露）：`src/agent/numkey.py`

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its line numbers
- find_replace(path, line, "old", "new") — replace "old" with "new" inside the line numbered `line` in `path`. "old" must be copied VERBATIM from that line and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the line, then try again. `line` refers to the CURRENT numbering, which shifts when earlier calls add or remove lines
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```

**ATTENTION_CLAUSE**（与 `patch_find_replace` 共享，保证稳定性是唯一变量）：
`src/agent/numkey.py`

```txt
Work in two passes before you emit any call.

Pass 1 — one block at a time. Go through the blocks in order and note what looks wrong inside each block on its own. Do not decide on any fix yet.

Pass 2 — across blocks. Now read the whole text. The same word, name or spelling usually appears more than once: where one occurrence is clean, it tells you how a garbled one elsewhere should read. Settle the notes from pass 1 with that evidence, and drop any you can no longer justify.

Then emit your calls.
```

**ONE_SHOT_NOTICE_TOOLS**（全部 neo 工具臂共有，永远在最后）：`src/agent/standard.py`

```txt
You have only ONE chance: this task gives you a single response — no feedback, no retry, no second turn.
Emit ALL your calls in this one response, with done() as the last line.
```

### 每轮对话

1-shot：只有第一轮。模型响应后不再有任何轮次——调用按顺序逐条执行，每条看到的
都是此前编辑重排后的编号（这是与 `patch_find_replace` 的执行语义差异所在）；
执行完即 extract（未以 `done()` 收尾记 `budget_exceeded`，产出照常评分）。

第一轮：

- system: 上方装配的五段拼接
- user: `--- INPUT (language: de) ---` + 行号视图 + `--- END OF INPUT ---`；
  视图 = 抬头 `--- [Text: text] ---` + 逐行 `N: 内容`（N = 位置性行号），
  由 `present_input` 产出——**外观与 patch_find_replace 的 num-key 视图逐字节同构**
- assistant（期望形态）：一口气给出全部调用，每条带目标行号，`done()` 收尾，例如

```txt
find_replace(text, 1, "brovvn", "brown")
find_replace(text, 2, "Thé quick", "The quick")
done()
```

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,patch_find_replace_unstable `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/dta19-doc-1shot-patch-find-replace-unstable --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace_unstable \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/dta19-doc-1shot-patch-find-replace-unstable --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `patch_find_replace_unstable` | **0.0104** | 0.0444 | 59.54% | 0.46% | 0.25% | 303.2 | 0.00% | 2.39M (91%r) | done 33 |

预期：行数变化（跨行合并/拆分的 over/under-segmentation 修复）之后的同批调用
key 漂移 ⇒ 「no line numbered」拒绝率与误改率高于 `patch_find_replace`；
若模型为规避漂移而自下而上排序调用，可观察到漂移损失收窄（磁带中可核查调用顺序）。

## 解读

<跑完填。对照 `dta19-doc-1shot-patch-find-replace`：唯一变量 = key 稳定性
（提示词披露方向 + 执行时重排），外观与其余条款全部相同。>

## 资产与备注

- 报告：`runs/dta19-doc-1shot-patch-find-replace-unstable/report.json`；磁带：`runs/dta19-doc-1shot-patch-find-replace-unstable/sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4-flash.toml` 未漂移。

# or-glm-dta19-doc-1shot-patch-find-replace-unstable

> 状态：待跑

实验单元（plan/neo_experiment.md 实验2 追加臂）：**doc 级、patch_find_replace 位置性
key 版（真行号、编辑后重排）、1 doc per session、1 shot** —— 与
`../dta19-doc-1shot-patch-find-replace-unstable` **配置逐字相同**，唯一变量是**模型**
（`volc-deepseek-v4-flash` → `openrouter-glm-5.3-flash`）。

与 `../glm-5.3-flash/` 批次的关系：**同模型**（GLM 5.3 Flash）**但不同端点**——
本批次走 OpenRouter，glm-5.3-flash 批次走火山引擎；**本单元** provider 路由锁
`parasail/fp8`。注意批次内 provider 是按单元分配的（modal / coreweave / parasail
三家，为绕开共享池限流），跨单元对照时 provider 是未控制变量，解读时需注明。
且本批次 `output_length = 393216` 与 volc 各单元对齐，**不存在** glm-5.3-flash 批次
`output_length = 131072` 那个已知的输出预算混淆项，可与蓝本直接对照。

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
    --model openrouter-glm-5.3-flash-parasail `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/or-glm-dta19-doc-1shot-patch-find-replace-unstable --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace_unstable \
    --model openrouter-glm-5.3-flash-parasail \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/or-glm-dta19-doc-1shot-patch-find-replace-unstable --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `patch_find_replace_unstable` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-patch-find-replace-unstable` 实际结果：
volc 中位 **0.0104** / max **0.0444** / fixed **59.54%** / broken **0.46%** /
halluc **0.25%** / edit_spans **303.2** / key_leak **0.00%** / out **2.39M（91%r）** /
status done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 位置性 key 的代价在换模型后仍可见：fixed / broken 与 volc 同量级（fixed ~59.5%、broken ~0.5%），且相对同模型 stable 臂（`../glm-5.3-flash/` 批次的 `patch_find_replace` 对照单元）呈同方向落差 | GLM 上 unstable 与 stable 两臂差距消失或方向反转 |
| 「no line numbered」漂移拒绝与 volc 同量级 | 拒绝率差出数量级 ⇒ 漂移损失主要是模型遵循披露的能力差异，不是接口性质 |
| `key_leak` 仍为 0 | GLM 泄漏 ⇒ 那条契约是模型特性不是提示词效果 |
| 无预算截断混淆：`output_length=393216` 与蓝本对齐，`incomplete` 计数应与蓝本同级（0） | 大面积 `incomplete` ⇒ 先查 OpenRouter/parasail-fp8 端点行为，再谈跨模型比较 |

## 解读

<跑完填。对照 ../dta19-doc-1shot-patch-find-replace-unstable：唯一变量 = 模型。>

要回答的三件事：

1. **key 漂移的代价是否复现** —— volc 上 unstable 臂中位 0.0104 / max 0.0444 /
   fixed 59.54% / broken 0.46%（蓝本预期：漂移 ⇒ 「no line numbered」拒绝率与
   误改率高于 `patch_find_replace`）。换模型后这些数字是否同量级：同量级 ⇒
   位置性 key 的咬人点是接口的性质；差很多 ⇒ 是模型对漂移披露的遵循能力差异。
2. **自下而上排序的规避策略** —— 蓝本预期：若模型为规避漂移而自下而上排序调用，
   漂移损失会收窄。磁带中核查 GLM 的调用顺序是否出现这种自组织行为，
   以及它是否解释了第 1 问观察到的差距。
3. **reasoning 占比与输出规模** —— volc 是 91%r / 2.39M out。
   若 GLM（OpenRouter/parasail-fp8）显著不同，则「可见输出的压缩优势被思考开销
   吞掉」这条结论要按模型/端点分别陈述。

## 资产与备注

- 报告：`runs/or-glm-dta19-doc-1shot-patch-find-replace-unstable/report.json`；磁带：`runs/or-glm-dta19-doc-1shot-patch-find-replace-unstable/sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/openrouter-glm-5.3-flash-parasail.toml` —— OpenRouter 端点，
  协议 `openai-response`，模型 `z-ai/glm-5.3-flash`，provider 路由经 extra_body
  锁定 `parasail/fp8`（不允许回退，回退会混量化变体与计费口径），
  `output_length = 393216`（与 volc 各单元对齐，消除 glm-5.3-flash 批次 128k
  预算的已知混淆项），`max_transport_retries = 8`。除模型外的一切
  （提示词五段、视图、工具、预算、数据）与蓝本单元逐字相同；
  跑前确认该 toml 未漂移。
- OpenRouter 共享池上游限流（429）较频繁，配置已把 `max_transport_retries`
  加深到 8；若仍有 failed cell，可经 resume 重试补齐，不必整批重跑。

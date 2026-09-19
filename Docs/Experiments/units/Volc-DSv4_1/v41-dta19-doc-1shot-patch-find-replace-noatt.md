# v41-dta19-doc-1shot-patch-find-replace-noatt

> 状态：已完成（2026-09-18）

实验单元（plan/neo_experiment.md 实验2 追加臂）：**doc 级、patch_find_replace 无注意力
条款版（num-key 定位）、1 doc per session、1 shot，num-key 视图** —— 与
`../dta19-doc-1shot-patch-find-replace-noatt` **配置逐字相同**，唯一变量是**模型版本**
（`deepseek-v4-flash` → `deepseek-v4.1-flash`）。

跨模型复现序列：volc deepseek-v4-flash（蓝本）→ OpenRouter GLM 5.3 Flash
（`../Openrouter-GLM-5_3/`）→ Packy Grok 4.6（`../Packy-Grok-4_6/`）→
**本批次 = 同端点模型版本升级**。本批次连端点都不变：同走火山
`https://ark.cn-beijing.volces.com/api/plan/v3`、同协议（openai-response）、
同上下文声明（1024k）、同输出预算（`output_length = 393216` = 384k，显式下发
max_output_tokens）——是历次复现中控制最严的一次，回答
「版本升级是否改变编辑接口层面的结论」。

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
    --model volc-deepseek-v4.1-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/v41-dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace_noatt \
    --model volc-deepseek-v4.1-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/v41-dta19-doc-1shot-patch-find-replace-noatt --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `patch_find_replace_noatt` | **0.0094** | 0.0276 | 60.96% | 0.41% | 0.23% | 340.5 | 0.00% | 1.31M (83%r) | done 33 |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-patch-find-replace-noatt` 蓝本实测：中位 0.0089 /
max 0.0621 / fixed 63.72% / broken 0.47% / halluc 0.28% / spans 317.7 /
key_leak 0.00% / 2.11M out tok（89% reasoning）/ done 33）——版本升级预期差异小，
若臂间排序、尾部形态、key_leak 等结构性质变了，那就是 v4.1 的行为变化：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位与 max 与 v4 同量级（0.0089 / 0.0621），臂间排序（noop > noatt）不变 | 排序反转，或中位 / max 显著偏离 ⇒ v4.1 的中心趋势或尾部行为变了 |
| 尾部形态保持：max 仍是带注意力版（0.0295）的两倍多 | 尾部显著收窄或拉宽 ⇒ 版本升级改变了 noatt 臂的尾部风险 |
| `key_leak` 仍为 0.00% | 出现泄漏 ⇒ 「num-key 不进文本」契约在 v4.1 上不再成立 |
| 截断样本 ≈ 0（同端点同 384k 预算，无混淆项） | 大面积 `incomplete` ⇒ 本单元不可与 v4 蓝本直接比 |
## 解读

跑后数据与跨版本对照汇总于批次报告 `../report/2026-09-18-doc-1shot-v41.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **版本升级是否改变编辑接口层面的结论** —— 蓝本（v4-flash）本臂中位 0.0089 /
   max 0.0621 / fixed 63.72% / broken 0.47% / halluc 0.28% / spans 317.7，
   去掉注意力条款后尾部显著拉宽（max 是带注意力版 0.0295 的两倍多）。
   若 v4.1 各数字同量级且结构性质（臂间排序、尾部形态）保持，
   则这些结论对版本升级稳健；变了则归因到 v4.1 本身。
2. **reasoning 占比** —— volc v4 本臂是 89%（2.11M out tok 中 89% 为 reasoning，
   约 90%+）。v4.1 待看：若显著不同，则「可见输出的压缩优势被思考开销吞掉」
   这条结论要按版本分别陈述。
3. **拒绝率** —— 「多匹配拒绝」与「未知 key」的比例是否与 v4 同量级。
   同量级 ⇒ 是接口的性质；差很多 ⇒ 是版本间遵循格式的能力差异。

## 资产与备注

- 报告：`runs/v41-dta19-doc-1shot-patch-find-replace-noatt/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/volc-deepseek-v4.1-flash.toml` —— 火山引擎端点
  （`https://ark.cn-beijing.volces.com/api/plan/v3`），协议 `openai-response`，
  模型 `deepseek-v4.1-flash`，`context_window = 1048576`（1024k，信息性），
  `output_length = 393216`（384k，显式下发为 max_output_tokens）。
  与 `configs/models/volc-deepseek-v4-flash.toml` 的唯一差异 = 模型名
  （`deepseek-v4-flash` → `deepseek-v4.1-flash`），其余逐字相同；
  除模型版本外的一切（提示词四段、视图、工具、预算、数据、端点）与蓝本单元逐字相同。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4.1-flash.toml` 未漂移。

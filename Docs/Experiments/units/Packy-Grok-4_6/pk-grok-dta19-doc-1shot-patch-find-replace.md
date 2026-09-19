# pk-grok-dta19-doc-1shot-patch-find-replace

> 状态：待跑

实验单元：**doc 级、patch_find_replace（num-key 定位）、1 doc per session、1 shot，
num-key 视图** —— 与 `../dta19-doc-1shot-patch-find-replace` **配置逐字相同**，
唯一变量是**模型**（`volc-deepseek-v4-flash` → `packy-grok-4.6`，Grok 4.6 经 Packy 中转）。

跨模型复现序列的第三个模型：volc-deepseek（蓝本）→ `../Openrouter-GLM-5_3/`
（GLM 5.3 Flash）→ 本批次（Grok 4.6）。与 `../Openrouter-GLM-5_3/` 批次互为
模型对照——同任务同配置、不同模型，意在回答「结论跨模型是否成立」。

## Tool

- 工具集：`src/agent/numkey.py::PatchFindReplaceToolSet`（注册键 `patch_find_replace`）
- 配置：`configs/toolsets/patch_find_replace.toml`（`max_turns=1`）
- 视图组件：`src/view/defaults.py::numkey`（`b12` → `"12"`，稳定 id）+ `cat_n`（`N: 内容`）；
  抬头经 `src/view/present.py::present_file`（`label="Text"`）

`find_replace(text, key, "old", "new")`：唯一性只在 num-key `key` 指定的块内判定
（0 或 >1 拒绝并回报冲突数）；未知 key 拒绝。编辑后回显被改块（key 不变）。
**只允许这一种编辑操作**：方言只认 `read` / `find_replace` / `done`，清单外操作
在 parse 层 ToolParseError（与 `patch_replace` 的 `allowed_ops` 同强度、同层拦截）。
IR-backed，num-key = BlockKey 序号，编辑不变更、不复用既有 key——
模型引用第一次看到的 key 永远有效。

## Context

### 系统提示词

装配（`src/agent/assembly.py::build_initial_messages`，逐字拼接）：

```text
system = BLOCR instruction
       + NUMKEY_VIEW_CLAUSE
       + PATCH_FIND_REPLACE_CLAUSE
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

**NUMKEY_VIEW_CLAUSE**（实验2 四臂共享的 view description）：`src/agent/numkey.py`

```txt
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output.
```

**PATCH_FIND_REPLACE_CLAUSE**（与 find_replace 条款逐行对照仅两处不同：
read 带 num-key；find_replace 多 `key` 参数、唯一性收窄到块内）：`src/agent/numkey.py`

```txt
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
- find_replace(path, key, "old", "new") — replace "old" with "new" inside the block with num-key `key` in `path`. "old" must be copied VERBATIM from that block and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the block, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```

**ATTENTION_CLAUSE**（与 `find_replace_blocked` 共享；本层叠档保持它与上一档一致，
隔离出的变量只有「用 key 定位」）：`src/agent/numkey.py`

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

1-shot：只有第一轮。模型响应后不再有任何轮次——调用执行完即 extract
（未以 `done()` 收尾记 `budget_exceeded`，产出照常评分）。

第一轮：

- system: 上方装配的五段拼接
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
    --toolsets noop,patch_find_replace `
    --model packy-grok-4.6 `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/pk-grok-dta19-doc-1shot-patch-find-replace --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_find_replace \
    --model packy-grok-4.6 \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/pk-grok-dta19-doc-1shot-patch-find-replace --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | | | | | | | | | |
| `patch_find_replace` | | | | | | | | | |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本 volc 单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-patch-find-replace` 已填的实测：volc 中位 **0.0084** /
max **0.0295** / fixed **65.80%** / broken **0.52%** / halluc **0.30%** /
spans **350.5** / key_leak **0.00%** / out tok **2.35M（90% reasoning）** / status done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 「中心趋势不可分、尾部分得开」在第三个模型上仍成立 | Grok 的尾部排序与 volc/GLM 对不上（结论不跨模型） |
| `key_leak` 仍为 0 | Grok 泄漏 ⇒ 那条契约是模型特性不是提示词效果 |
| 输出预算不是混淆项：393216 与 volc 对齐，`incomplete` 应为 0 | 出现截断 ⇒ 先查端点实际下发预算，再谈比较 |
| status 全部 `done 33`（中转不稳时经 resume 补齐 failed cell） | 残余 failed ⇒ 重试通道仍不够，先补跑再解读 |

## 解读

<跑完填。对照 ../dta19-doc-1shot-patch-find-replace：唯一变量 = 模型。>

要回答的三件事：

1. **中位与尾部的排序在第三个模型上是否保持** —— 蓝本最强的结论
   （中心趋势跨度 1.4×、尾部跨度 33×）已有 volc、GLM 两张票，Grok 是第三张。
2. **reasoning 占比与可见输出量** —— volc 约 90% reasoning（2.35M out tok，
   可见输出中位 ~4.7k/task）；GLM 可见输出比 deepseek 啰嗦约 6 倍
   （中位 ~27.7k/task）。Grok 待看：若三者各不相同，「可见输出的压缩优势被
   思考开销吞掉」这条结论必须按模型分别陈述。
3. **拒绝率** —— 「多匹配拒绝」与「未知 key」的比例是否与 volc/GLM 同量级。
   同量级 ⇒ 是接口的性质；差很多 ⇒ 是模型遵循格式的能力差异。

## 资产与备注

- 报告：`runs/pk-grok-dta19-doc-1shot-patch-find-replace/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/packy-grok-4.6.toml` —— Packy 中转端点
  （`https://cf.api.fan/v1`），协议 `openai-response`（该模型不支持
  chat/completions，实测 `protocol_not_supported`），模型 `grok-4.6`；
  `output_length=393216`，与 volc 各单元逐字对齐；`max_transport_retries=8`，
  与 OpenRouter 批次同深度。
- 中转注入已验证无泄漏：该中转在不带 instructions 的请求里会注入一段默认
  Codex CLI 系统提示词；本单元每条请求都自带 instructions（五段 system 拼接），
  实测注入被整体替换、无泄漏（input_tokens 从 4632 回落到正常量级）。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/packy-grok-4.6.toml` 未漂移。

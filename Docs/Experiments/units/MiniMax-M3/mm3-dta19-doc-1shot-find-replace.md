# mm3-dta19-doc-1shot-find-replace

> 状态：已完成（2026-09-19）

实验单元：**doc 级、find_replace、1 doc per session、1 shot** —— 与
`../dta19-doc-1shot-find-replace` **配置逐字相同**，唯一变量是**模型**
（`deepseek-v4-flash` → `MiniMax-M3[1m]`，配置键 `minimax-m3-1m`）。

跨模型复现序列中的位置：volc deepseek-v4-flash（蓝本）→ Openrouter GLM 5.3 Flash
（`../Openrouter-GLM-5_3/`）→ Packy Grok 4.6（`../Packy-Grok-4_6/`）→
volc deepseek-v4.1-flash（`../Volc-DSv4_1/`）→ **本批次 = 新厂商新模型 +
新端点 + 新协议**。本批次走 MiniMax 官方 Anthropic 兼容端点
（`https://api.minimax.cn/anthropic`），模型 `MiniMax-M3[1m]`——是复现序列中
**第一个 anthropic 协议批次**（此前全部为 openai-completion / openai-response）。
两个由此而来的口径差异：(a) system 提示词经顶层 `system` 字段下发，而非
messages 首条；(b) Anthropic 口径不单列 reasoning token——usage 里 reasoning
含在 output_tokens 内（`reasoning_tokens=None`），与 volc / OpenRouter 批次
「out tok (xx%r)」直接比 reasoning 占比不可行，只能比总 output token。
声明性预算与上一批逐字对齐：`context_window=1048576`（1024k，信息性）、
`output_length=393216`（384k，anthropic 协议强制下发为 max_tokens）；
采样参数留空 = 不下发。与上一批「连端点都不变」相反，本批次**端点与协议是
未控制变量**：显著偏离先归端点/协议，再归模型。本批次回答的问题仍是蓝本批次
报告 `../report/2026-09-08-doc-1shot.md`「缺口」节指出的那条：全部结论目前
只是少数模型上的性质。

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
    --model minimax-m3-1m `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/mm3-dta19-doc-1shot-find-replace --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace_anthropic_style \
    --model minimax-m3-1m \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/mm3-dta19-doc-1shot-find-replace --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `find_replace_anthropic_style` | **0.0232** | 0.0621 | 11.39% | 0.13% | 0.05% | 53.2 | 0.00% | 146k | budget_exceeded 18, done 15 |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-find-replace` 蓝本实测：v4 中位 0.0096 / max 0.0605 /
fixed 61.26% / broken 0.46% / halluc 0.26% / spans 254.5 / key_leak 0.00% /
out 2.12M（91%r）/ done 33；第二参照 `../Volc-DSv4_1/` 实测：中位 0.0101 /
max 0.0582 / fixed 58.86% / broken 0.44% / halluc 0.21% / spans 304.9 /
key_leak 0.00% / out 1.43M（88%r）/ done 33）：

| 预期 | 什么结果算预期落空 |
|---|---|
| 中位 / fixed 与蓝本接近（0.0096 / 61.26% 附近，第二参照 0.0101 / 58.86%），臂间排序不变（find_replace 仍优于 rewrite 的中位 0.0120 一档） | 中位或 fixed 大幅偏离 ⇒ 中心趋势变了；端点/协议未控制，先归端点协议（新厂商、anthropic 协议、system 字段口径），再归模型 |
| 尾部形态保持蓝本量级（max ≈ 0.0605，无灾难型样本） | max 蹿到 rewrite 式灾难量级（蓝本批次 rewrite max 0.9648）⇒ 出现了 v4 / Volc-DSv4_1 都没有的尾部失败，先查端点截断与协议行为再归模型 |
| `key_leak` 维持 0.00%（蓝本批次八单元全场为零；本单元输入无 num-key） | 任何非零值 ⇒ 先查视图/装载漂移 |
| 调用拒绝率与 v4 同量级（1-shot 下被拒即作废，直接压低 fixed） | 拒绝率显著变化 ⇒ 模型间遵循方言/格式的能力差异，不是接口性质 |
| 截断样本 = 0（output_length=393216 与蓝本逐字对齐，anthropic 协议强制下发为 max_tokens；蓝本 done 33 无截断） | 出现 `incomplete`/`budget_exceeded` 异常 ⇒ 先查 MiniMax 端点对 max_tokens 的实际下发行为，再谈比较 |
## 解读

跑后数据与跨批次对照汇总于批次报告 `../report/2026-09-19-doc-1shot-mm3.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **编辑接口层面的结论在换模型（+ 新端点/协议）后是否保持** —— 蓝本批次的核心
   发现（接口差异在中心趋势上不可分、尾部差 33 倍；find_replace fixed 61.26% /
   broken 0.46% / max 0.0605）此前只是 v4-flash 的性质，`../Volc-DSv4_1/` 已在
   同端点版本升级下复现（中位 0.0101 / max 0.0582）。本批次若臂间排序、尾部
   形态、key_leak 等结构性质变了，不能归因于接口或预算——但端点/协议是
   未控制变量，先归端点协议，再归模型。
2. **输出 token 总量** —— volc v4 out 2.12M（91%r），`../Volc-DSv4_1/` 1.43M
   （88%r）。本批次 anthropic 口径不单列 reasoning token（含在 output_tokens
   内，`reasoning_tokens=None`），reasoning 占比不可与既有批次直接比，只能比
   总 output token：总量若显著不同，「可见输出的压缩优势被思考开销吞掉」
   这条结论要按口径限制重新陈述。
3. **拒绝率** —— 「不唯一/不匹配拒绝」在 1-shot 下被拒即作废。与 v4 /
   `../Volc-DSv4_1/` 同量级 ⇒ 是接口的性质；差很多 ⇒ 是模型遵循格式的
   能力差异。

## 资产与备注

- 报告：`runs/mm3-dta19-doc-1shot-find-replace/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/minimax-m3-1m.toml` —— MiniMax 官方 Anthropic 兼容端点
  （`https://api.minimax.cn/anthropic`），协议 `anthropic`（POST /v1/messages，
  x-api-key 鉴权），模型 `MiniMax-M3[1m]`；`context_window=1048576`
  （1024k，信息性），`output_length=393216`（384k，anthropic 协议强制下发为
  max_tokens）；采样参数留空 = 不下发，用端点默认。凭证 `MINIMAX_API_KEY`
  在项目根 `.env`。除模型外的一切（提示词三段、视图、工具、预算、数据）
  与蓝本单元逐字相同。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/minimax-m3-1m.toml` 未漂移。

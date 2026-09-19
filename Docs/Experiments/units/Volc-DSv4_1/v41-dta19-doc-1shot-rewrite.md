# v41-dta19-doc-1shot-rewrite

> 状态：已完成（2026-09-18）

实验单元（plan/neo_experiment.md 实验1）：**doc 级、rewrite、1 doc per session、1 shot** ——
与 `../dta19-doc-1shot-rewrite` **配置逐字相同**，唯一变量是**模型版本**
（`volc-deepseek-v4-flash` → `volc-deepseek-v4.1-flash`，即 `deepseek-v4-flash` →
`deepseek-v4.1-flash`）。

与此前复现批次的关系：这是复现序列（volc deepseek-v4-flash 蓝本 → OpenRouter
GLM 5.3 Flash → Packy Grok 4.6 → **本批次**）中控制最严的一次 —— **同端点**
（火山 `https://ark.cn-beijing.volces.com/api/plan/v3`）、同协议（`openai-response`）、
同上下文声明（1024k）、同输出预算（`output_length = 393216` = 384k，显式下发
`max_output_tokens`），连端点都不变，只有模型版本号。回答的问题：版本升级是否改变
编辑接口层面的结论。

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
    --model volc-deepseek-v4.1-flash `
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc `
    --out runs/v41-dta19-doc-1shot-rewrite --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_anthropic_style \
    --model volc-deepseek-v4.1-flash \
    --split dev --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc \
    --out runs/v41-dta19-doc-1shot-rewrite --workers 11
```

## 结果

| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |
|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0659 | 0.00% | 0.00% | 0.00% | 0.0 | 0.00% | 0k | done 33 |
| `rewrite_anthropic_style` | **0.0104** | 0.0605 | 65.04% | 0.65% | 0.26% | 304.8 | 0.00% | 985k (84%r) | done 33 |

`noop` 与模型无关，中位应为 **0.0238**、max **0.0659** —— 与蓝本单元一致；
不一致即数据装载或评分口径漂移，先查这个再看别的。

预期（对照 `../dta19-doc-1shot-rewrite` 的实际结果：v4 中位 **0.0120** /
max **0.9648** / fixed **67.42%** / broken **3.86%** / halluc **0.51%** /
spans **343.8** / key_leak **0.00%** / out tok **1.88M（93%r）** / done 33）：
版本升级预期差异小，臂间排序与结构形态应与蓝本保持一致。

| 预期 | 什么结果算预期落空 |
|---|---|
| rewrite 臂 vs noop 臂的排序不变（v4：中位 0.0120 < 0.0238），fixed 量级与 v4 相近 | v4.1 的 fixed 大幅偏离 67.42%（如掉到 find-replace 类臂量级）或排序反转 |
| 尾部形态不变：v4 max 冲到 0.9648、broken 3.86%（远高于 find-replace 类臂的 0.52%） | v4.1 尾部收敛（max 大幅下降、broken 归零量级）⇒ 版本升级改变了重写失控形态 |
| 破坏以漏抄（broken_del）为主这一形态不变 | 破坏结构换成 halluc 或截断主导 |
| `key_leak` 恒为 0（输入无 num-key，v4 实测 0.00%） | 任何非零值 ⇒ 先查视图/装载漂移 |
| 噪声越高越容易输出截断（`incomplete`）的梯度仍在 | 大面积 `incomplete` 与噪声档脱钩 ⇒ 先查端点/限流，再谈比较 |
## 解读

跑后数据与跨版本对照汇总于批次报告 `../report/2026-09-18-doc-1shot-v41.md`；本单元特有信号见该报告对应条目。下方为跑前写下的待答问题，逐条答案见报告。

要回答的三件事：

1. **rewrite 臂的「fixed 不低、尾部失控」在版本升级后是否保持** —— v4 上
   中位 0.0120 但 max 冲到 0.9648、broken 3.86%（远高于 find-replace 类臂的 0.52%），
   「整篇重写的破坏以漏抄为主、尾部随噪声放大」这条结论此前只在 v4 单版本上验证过。
   若 v4.1 臂间排序、尾部形态改变，那就是版本升级带来的行为变化。
2. **reasoning 占比** —— v4 约 90%+（out tok 1.88M，93%r）。v4.1 待看；若显著不同，
   「rewrite 的输出预算大头花在思考上」这条结论要按版本分别陈述。
3. **截断与噪声的耦合** —— v4 上噪声越高越容易 `incomplete`。本单元
   output_length 与 v4 逐字对齐（393216）且同端点，若 v4.1 在同样预算下截断分布不同，
   差异应归因于版本间的输出长度行为而非预算或端点配置。

## 资产与备注

- 报告：`runs/v41-dta19-doc-1shot-rewrite/report.json`；磁带：同目录 `sessions/`
- 数据：dta19 三噪声档（l0/l1/l2，同一批 11 篇加噪）× doc 粒度，33 task × 2 arm。
- 模型：`configs/models/volc-deepseek-v4.1-flash.toml` —— 火山引擎端点
  （`https://ark.cn-beijing.volces.com/api/plan/v3`）、协议 `openai-response`、
  1024k 上下文声明、`output_length = 393216`（384k，显式下发 `max_output_tokens`）。
  与 `configs/models/volc-deepseek-v4-flash.toml` 的唯一差异 = 模型名
  （`deepseek-v4-flash` → `deepseek-v4.1-flash`），其余逐字相同。除模型版本外的一切
  （端点、协议、提示词三段、视图、工具、预算、数据）与蓝本单元逐字相同。
- 跨单元对照要求模型配置一致：跑前确认 `configs/models/volc-deepseek-v4.1-flash.toml`
  与 `configs/models/volc-deepseek-v4-flash.toml` 除模型名外均未漂移。

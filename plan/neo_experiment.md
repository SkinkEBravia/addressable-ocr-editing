根据上次实验设计的问题，重新设计的实验

## tool 说明

### view 的统一结构

```
<path 抬头>
<annotated 内容>
```

- **path**：处理对象的名字，跨轮稳定。所有工具用它寻址「改哪一份」。
  单文档场景只有一个 path；`seq-global` 下每个单元一个 path。
- **annotated**：实验1 为纯原文；实验2 每块前缀一个 **num-key**。

### num-key

```
1: Thé quick brovvn fox jumps
2: over the lazy dog
```

**num-key 是稳定标识，不是行号。** 编辑后不重排 —— 一个块的 key 在整场对话里不变，
模型可以放心引用第一次看到的 key。

用行号会引入一个隐藏操作：模型必须预判自己前面的编辑造成的位移。稳定 key 消除它。
⚠️ 提示词里必须写明「不是行号」，否则模型会按行号的直觉去推算。

### 三个工具

| 工具 | 签名 | `old` 的唯一性范围 |
|---|---|---|
| `find_replace` | `find_replace(path, "old", "new")` | 整个 path |
| `patch_find_replace` | `find_replace(path, key, "old", "new")` | **该 num-key 的块内** |
| `swe_edit` | `edit(path, start, end, "text")` | 无字符串匹配，直接按行号换整段 |

`find_replace` 两个变体的唯一差别是**搜索范围**：全 path vs 单块。
其余（逐字复制、不唯一则拒绝执行并回报、JSON 字符串）完全相同。

`find_replace` 对齐 Anthropic `str_replace`（`old_str` 必须唯一，不唯一拒绝执行）。
`swe_edit` 对齐 SWE-agent classic 的行号锚 —— 它的行号**是**位置性的、会漂移，
这是该臂的固有性质，不修正。


## 实验1：探究输出阶段完整遍历注意力窗口与聚焦发现的错误的差异

上下文管理：

- system: BLOCR 提示词
  - find_replace 在最后追加 tool prompt
- first_user_message: 修复对象，均为原文

view: 纯原文

### 设计

**要回答的问题**：让模型把全文重新输出一遍，和只让它输出「哪里改成什么」，哪个更好？

| 臂               | 怎么交付修改                     |
| ---------------- | -------------------------------- |
| `noop`         | 不修，作为「不动它会怎样」的对照 |
| `rewrite`      | 把整篇修好的文本重新写一遍       |
| `find_replace` | 只输出「把 old 换成 new」的指令  |

两边看到的输入**完全一样**（都是纯原文），system 提示词的公共部分、轮数预算、模型也一样。
唯一的差别就是交付方式 —— 所以结果差异只能归因于它。

- 数据：`dta19` 的 l0 / l1 / l2 三个噪声档 × 整篇粒度，每档 11 篇德语文档
  （同一批文档人工加噪到三个程度，所以噪声是唯一变化的因子）
- 每篇看这几个数：
  - **cmer** —— 字符错误率，越低越好。**看中位数，不看平均**：上一批有一篇文档
    把某个臂的平均值带偏了 4.7 倍，平均数会撒谎
  - **最差那一篇（max）** —— 单独看。中位数说「典型情况」，max 说「最坏情况」
  - **修对了多少 / 改坏了多少**
  - **改坏的方式**：改错了 / 漏抄了 / 凭空加了字
  - **实际改动了多少个地方**（由原文和产出对比得出，两个臂都能算）
  - token 消耗

> [!note] ✏️ 这两个臂的数据可能已经有了
> 上一批实验里 `rewrite` 和 `find_replace` 本来就都拿纯原文，是公平的
> （不公平的是另外两个臂，它们的输入带标记）。
> ⇒ **先翻已有结果，只有在要统一新 system 提示词时才重跑**（约 3M token）。

**跑之前先写下预期**（跑完逐条对账，防止事后编故事）

| 预期                                                                              | 什么结果算预期落空     |
| --------------------------------------------------------------------------------- | ---------------------- |
| 两个臂「修对多少」差不多（因为找错误的方式一样），差别集中在「改坏多少」          | 修对的差距反而更大     |
| `rewrite` 改坏的主要方式是**漏抄**，`find_replace` 主要是**改错** | 两者方式相同           |
| `rewrite` 的最坏一篇更糟（max 相对中位数拉得更开）                              | 最坏情况相当，或反过来 |
| 噪声越高，`rewrite` 越容易因为输出太长被截断                                    | 截断率和噪声无关       |

### Coding Plan（简要）

新建，不改既有实现（旧臂要留给既有 run 读回）。

| # | 做什么 | 落点 |
|---|---|---|
| 1 | **path 抬头的 view**：`--- [Text: {name}] ---` + 原文 | `src/view/present.py::present_file`（`prefix=None`、`annotator` 恒等） |
| 2 | **`find_replace_anthropic_style`**：`find_replace(path, "old", "new")`，`count(old)` 不等于 1 即拒绝并回报冲突数 | `src/agent/standard.py`，照 `FindReplaceToolSet` 复制一份改 `_find_replace` |
| 3 | **`rewrite_anthropic_style`**：仅把输入换成带 path 抬头的 view，输出仍是纯文本 | 同上 |
| 4 | 注册 + 两个 toml | `src/agent/config.py`、`configs/toolsets/` |
| 5 | 测试：唯一→成功、零匹配→拒绝、多匹配→拒绝且不改动 | `tests/test_agent.py` |

第 2 项现有实现只差一个分支：

```python
count = text.count(old)
if count == 0:  return ToolResult(False, f"PATTERN_NOT_FOUND: {old!r} does not occur")
if count > 1:   return ToolResult(False, f"Found {count} matches for {old!r}. Please provide more context to make a unique match.")
```

**先翻已有 dta19 数据** —— `rewrite` 与 `find_replace` 当时都拿纯原文，本就公平。
只有确认要统一新 system 前缀时才跑新臂。


## 实验2：探究锚对结果的影响 + 按锚点聚焦的影响

上下文管理：

- system: BLOCR 提示词 + **view description（四臂共享）** + 各臂的 tool prompt
  - rewrite：无 tool prompt
  - find_replace：tool prompt
  - find_replace_blocked：tool prompt + 注意力控制提示词
  - patch_find_replace：tool prompt + 注意力控制提示词
- first_user_message: 打有 num-key 的原文。num-key 不是文本的一部分，各臂产出的都是不带 key 的纯文本。

### 设计

**要回答的问题**：给原文打上 num-key 有什么用？分三种用法，一层层加。

| 臂 | 输入带 key | 提示词要求先按块想 | 改的时候用 key 定位 |
|---|---|---|---|
| `rewrite` | ✅ | — | — |
| `find_replace` | ✅ | — | — |
| `find_replace_blocked` | ✅ | ✅ | — |
| `patch_find_replace` | ✅ | ✅ | ✅ |

**每一档只比上一档多一样东西**，所以每两档之间的差就是那一样东西的效果：

| 比什么 | 得到什么 |
|---|---|
| 实验1 的 `find_replace` ↔ 实验2 的 `find_replace` | key **光是看得见**（用不上）有没有影响 |
| `find_replace` ↔ `find_replace_blocked` | **提示词让它按块想**有没有影响 |
| `find_replace_blocked` ↔ `patch_find_replace` | **真的拿 key 去定位**有没有影响 |

第一条尤其要紧：如果 key 光是出现在输入里就改变了结果，那上一批实验里
「带标记的臂 vs 不带标记的臂」全部不可比，得重做。

**三个必须先定的实现细节**

1. **num-key 稳定，不重排。** 编辑后一个块的 key 不变。否则模型必须预判自己前面的
   编辑造成的位移 —— 那是一个提示词没说、却必须做的隐藏计算。
2. **各臂产出都是纯文本。** key 不是文本的一部分，谁也不用回抄。
   单独记一个「**key 泄漏进产出**」的数，不混进「改坏了多少」——
   `rewrite` 最可能泄漏，这是可量化的指令遵循问题。
3. `patch_find_replace` 只允许 `find_replace` 一种操作，**在解析阶段真的拒绝**其他操作。
   只在提示词里不写是不够的 —— 那样模型照样能用，名字就成了假的。

- 数据和指标同实验1
- 成本：3 个臂 × 3 个噪声档 × 11 篇 ≈ **4.5M token**

**跑之前先写下预期**

| 预期 | 什么结果算预期落空 |
|---|---|
| key 光看得见不影响 `find_replace`（和实验1 同臂结果一致） | 有明显差异 ⇒ 上一批的跨臂比较要全部重做 |
| 要求按块想会让它改得更少：改坏减少，修对也减少 | 两者同方向变化 |
| 真的用 key 定位后，**每次操作波及的范围变小** | 不变或变大 |
| `rewrite` 的 key 泄漏率高于其他臂 | 各臂泄漏率相当 |

### Coding Plan（简要）

依赖实验1 的第 1~2 项。

| # | 做什么 | 落点 |
|---|---|---|
| 1 | **稳定 num-key 的 id 策略**：`AgentBlockId = int(BlockKey[1:])`。BlockKey 形如 `b12`，跨编辑不变 ⇒ key 天然稳定、不重排。**不要用 `line_number`**（位置性、会重排） | `src/view/defaults.py` 新增 `numkey` |
| 2 | **annotator**：`f"{key}: {content}"`（沿用现有 `cat_n` 的形式，不要改成 `cat -n` 的制表符版） | 复用 `src/view/defaults.py::cat_n` |
| 3 | **view**：path 抬头 + 上面两项 | `present_file(snapshot, name, annotator=cat_n)` + `numkey` 策略 |
| 4 | **`patch_find_replace_anthropic_style`**：`find_replace(path, key, "old", "new")`，唯一性只在该块内判定 | `src/agent/patch.py` 旁新建，不改 `PatchToolSet` |
| 5 | **parse 层拒绝**清单外操作（沿用已实现的 `allowed_ops`） | 同上 |
| 6 | **`find_replace_blocked`** = 实验1 的 `find_replace_anthropic_style` + 注意力控制条款；工具行为完全不变 | 只加 `prompt_clause`，不新增工具逻辑 |
| 7 | **key 泄漏指标**：产出里若出现 `^\d+: ` 形态的前缀即计数，**单列，不进 `broken`** | `datasets/hipe_2026/dataset.py` 的 `_score_unit` |
| 8 | 注册 + 三个 toml + 测试 | `config.py` / `configs/toolsets/` / `tests/` |

**第 1 项是本实验成立的前提。** 用 `line_number` 会让模型必须预判自身编辑造成的位移 ——
那是一个提示词没说、却必须做的隐藏计算，会把「按 key 定位」的效果和「会不会算位移」混在一起。

**第 6 项要注意**：`find_replace` 与 `find_replace_blocked` 必须共用**同一个工具实现**，
只有 `prompt_clause` 不同。否则这一对隔离的就不是提示词了。


## 实验3：探究不同锚对结果的影响

**等实验2 出结果再设计。** 锚的形式取决于实验2 里 num-key 是否真的起作用。

## appendix

下面四段都是**照抄现有实现**，未做任何修改，供比对与修订。
来源已注明；改动后请同步回源文件，否则实验跑的和这里写的不是一回事。

### BLOCR 提示词

官方 BLOCR SYSTEM_PROMPT 的指令体逐字副本。
源：`datasets/hipe_2026/instruction.md`（由 `default_instruction()` 读取）

```text
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

### view description（共享）

**实验2 的四个臂共用这一段**，追加在 BLOCR 之后、各自的 tool prompt 之前。
只给用 key 的臂解释 key，另外三臂就看到一堆没解释的数字 —— 那是混淆项。

```text
Each block of the text is prefixed by a num-key:

  <num-key>: <block content>

A num-key is a STABLE identifier, NOT a line number. Keys are never renumbered:
a block keeps its key for the whole session, no matter how many replacements you
make. Do not try to predict how your own edits shift anything — just use the key
you saw. The keys are not part of the text; never include them in what you output.
```

实验1 无 key，此段留空。


### find_replace tool prompt

对齐 Anthropic `str_replace` 的唯一性语义。改完同步 `src/agent/standard.py`。

```text
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path`
- find_replace(path, "old", "new") — replace "old" with "new" in `path`. "old" must be copied VERBATIM from the text and must match EXACTLY ONE place in `path`. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```


### patch_find_replace tool prompt

在 `find_replace` 上只加一个 num-key 参数，唯一性范围从整个 path 收窄到该块。
视图说明见上方**共享**的 view description。

```text
You edit the text with tool calls, one function call per line:
- read(path) — return the current text of `path` with its num-keys
- find_replace(path, key, "old", "new") — replace "old" with "new" inside the block with num-key `key` in `path`. "old" must be copied VERBATIM from that block and must match EXACTLY ONE place in it. If it does not occur, or occurs more than once, the call FAILS and nothing is changed — include enough surrounding context in "old" to make it unique within the block, then try again.
- done() — finish; the current text becomes the output. May stand alone or be the last line after your calls

Strings use JSON syntax. Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately.
```

> 与 `find_replace` 逐行对照，只有两处不同：`read()` 的返回带 num-key；
> `find_replace` 多了 `key` 参数，唯一性范围随之收窄到该块。


### 注意力控制提示词

追加在 `find_replace_blocked` 与 `patch_find_replace` 的 tool prompt 之后。
两遍：先逐块收敛注意力，再放开做跨块推理。

```text
Work in two passes before you emit any call.

Pass 1 — one block at a time. Go through the blocks in order and note what looks wrong inside each block on its own. Do not decide on any fix yet.

Pass 2 — across blocks. Now read the whole text. The same word, name or spelling usually appears more than once: where one occurrence is clean, it tells you how a garbled one elsewhere should read. Settle the notes from pass 1 with that evidence, and drop any you can no longer justify.

Then emit your calls.
```

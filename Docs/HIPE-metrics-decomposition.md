# HIPE 分解指标设计：fixed / broken / missed / 幻觉分量

> 状态：草稿（未实现）。数据集特有设计，放在 Docs 根目录而非 Design/。
> 背景：官方指标体系（cmer_micro/macro、wmer、pref_score）不含幻觉与过修度量，
> MER 公式甚至刻意对幻觉脱敏（插入计入分母）；而对抗这两者是官方承认的未来工作。
> 本设计在 `datasets/hipe_2026/dataset.py` 的 scorer 内扩展，不改框架与官方代码。

## 一、如何分离

### 三个文本、两次对齐

- `I` = OCR 原文（task.input）
- `H` = 模型产出（prediction）
- `G` = 参考金标（task.reference）

用 jiwer 的字符级对齐（官方 scorer 同款，`process_characters`，归一化口径与官方
cmer 一致）做两次：

```text
对齐 A：G ↔ I   —— 每个金标位置上，原文是对是错
对齐 B：G ↔ H   —— 每个金标位置上，产出是对是错
```

### 逐金标位置的 2×2 分类

遍历 G 的每个字符位置，按两次对齐的状态分类：

| | H 对 | H 错 |
|---|---|---|
| **I 对** | kept（未动，正确） | **broken（过修：对的改错）** |
| **I 错** | **fixed（修复：错改对）** | **missed（欠修：错仍错）** |

「错」在对齐里 = 该位置为替换（S）或删除（D）；「对」= 命中（H）。

### 插入 run 的归属（原文自带多余字符 vs 模型主动新增插入）

插入（I）不对齐任何金标位置，单独按锚点与增量归属：

1. **原文自带的插入（$ins_I$）**：计入 $errors_I$（OCR 自身的幻象/多余字符）。
   - H **保留**了这些插入：属于欠修未改，记为 **fixed-none / missed-ins**；
   - H **删除**了这些插入：成功剔除原文多余字符，记为 **fixed-ins-del**。
2. **H 相对 I 主动新增的插入（$\max(0, ins_H - ins_I)$，按 gap 计数重叠）**：
   全部记为 **broken-ins（模型引入的幻觉）**。
   补上原文缺失字符的修复由 2×2 表的 fixed-del 承担（H 在 I 删除处对齐正确），
   不单列 fixed-ins。

同理，H 相对 G 的**删除**里：删掉「I 中的错误内容」是修复（fixed-delete），
删掉「I 中正确的内容」是内容丢失（broken-delete，幻觉的另一面）。

### 产出计数

```text
fixed   = fixed-sub + fixed-del + fixed-ins-del  # 修对的（含改对、补缺、剔除原文多余字符）
broken  = broken-sub + broken-del + broken-ins               # 改错 + 幻觉（改坏、误删、凭空多写）
missed  = missed-sub + missed-del + missed-ins               # 没修掉的（替换未改、缺字未补、多字未删）
kept    = 原本正确且未被触碰的
```

错误基数（归一化分母）：
- `errors_I` = I 相对 G 的 (S + D + I) —— 原文总错误数
- `correct_I` = I 相对 G 的 hits —— 原文正确的字符数

### 指标（ScoreRecord 新增键，报告自动按名聚合）

| 键 | 定义 | 读法 |
|---|---|---|
| `fixed_rate` | fixed / errors_I | 修复召回：原文的错修掉了几成 |
| `broken_rate` | broken / correct_I | 过修率：原本正确的内容被改坏几成 |
| `halluc_ins` | broken-ins / (len(G) + ins_H) | 幻觉（插入）占比 |
| `missed_rate` | missed / errors_I | 欠修率 |
| `cmer` | 现有官方口径，不变 | 净效果（对照用） |

不变式（自检用）：`fixed + missed ≡ errors_I`（原错只有修掉与没修掉两种归宿）；
`cmer` 与 `(S+D+I)_H` 的合计必须等于官方口径的结果。

聚合口径与官方一致：micro = 先按单元合计计数再算比率（macro 另列，不混排）。

## 二、合成用例验证（设计自检，待实现时做）

- 完美修复：H == G ⇒ fixed = errors_I，broken = 0，幻觉 = 0
- noop：H == I ⇒ fixed = 0，broken = 0，missed = errors_I
- 纯幻觉：H = I + 一段凭空插入 ⇒ broken-ins > 0，fixed = 0
- 过修：H 把 I 中正确处改错 ⇒ broken-sub > 0

## 三、实现位置与边界（待写）

`datasets/hipe_2026/dataset.py` 的 scorer 扩展；jiwer 复用官方 scorer 依赖。

## 四、报告呈现（待写）

分解表：指标 × arm；配对比较沿用 evalkit 的 bootstrap CI。

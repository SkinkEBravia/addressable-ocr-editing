# dta19-doc-1t

> 状态：已完成（2026-09-04）

## 问题

整篇长文档单轮修复（平均 ~14.4k 字符 / ~4.1k BPE tokens）：
1. 第一轮对话直接给出拼接后的完整文档，单轮一次性修复；
2. 在大上下文且极端低错误率（0.36%）的场景下，rewrite 是否会因全文重写造成严重的过修与幻觉漂移？
3. patch、swe_edit 与 find_replace 三种编辑形态在 4k tokens 上下文下的定位精度与资源开销对比。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite | 单轮长文重写 | 全文一次性重写；JSON 条款 |
| patch-1turn | 整篇块 id 补丁 | 单轮行划分 patch（约 300~400 行）；**apply_mode=best_effort**，未隐去任何操作（全部七个 SurfaceOp）。原以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，已用磁带重放修正 —— 见 [[shit#11. 实验记录里的配置描述与 toml 不符]] |
| swe_edit | 整篇行号编辑 | 单轮行号区间替换（edit start:end "text"） |
| find_replace | 整篇字符串替换 | 单轮字面字符串匹配替换（find_replace "old" "new"） |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc `
    --out runs/dta19-doc-1t --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc \
    --out runs/dta19-doc-1t --workers 11
```


> [!danger] 配置更正（2026-09-06）
> 本记录初版把 `patch-1turn` 写成 "best_effort + 隐去 append/merge"，**与实际运行的
> `configs/toolsets/patch-1turn.toml` 不符** —— 该文件既未设 `apply_mode`（⇒ 默认 **atomic**），
> 也未设 `hide_ops`。那段描述实际对应的是从未在本 run 使用的 `patch-1turn-lenient.toml`。
>
> **后果**：atomic 下批次内任一 `replace` 的 `old` 匹配不上（`PATTERN_NOT_FOUND`）即**整批回滚**。
> 磁带实测每-op 失败率仅 0.24%~1.27%，却因连坐作废了 19.5%~83.7% 的已提交 op。
> **本记录中 `patch-1turn` 的全部数字都受此影响。**

## 结果

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[shit#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0037** | 0.0040 [0.0031, 0.0052] | 0.0060 | **0.0081** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite` | **0.0058** | 0.0075 [0.0046, 0.0109] | 0.0114 | **0.0216** | 44.81% | 0.53% | 0.32% | 49.7 | 567.5k | 91.5% |
| `patch-1turn`〔best_effort〕 | **0.0040** | 0.0051 [0.0036, 0.0069] | 0.0082 | **0.0123** | 27.28% | 0.22% | 0.18% | 25.5 | 383.5k | — |
| `swe_edit` | **0.0062** | 0.0289 [0.0048, 0.0751] | 0.0114 | **0.2579** | 42.16% | 2.85% | 0.86% | 145.6 | 557.2k | 98.1% |
| `find_replace` | **0.0045** | 0.0050 [0.0037, 0.0063] | 0.0078 | **0.0090** | 41.35% | 0.27% | 0.22% | 38.6 | 589.9k | 98.7% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite` | 3.7 | 32.9 | 56.4 | 35.4% |
| `patch-1turn` | 3.3 | 1.5 | 17.3 | 7.0% |
| `swe_edit` | 147.6 | 77.8 | 105.7 | 23.5% |
| `find_replace` | 3.2 | 2.7 | 36.5 | 6.4% |

## 读法与结论

1. **低噪（L0）整篇：`patch` 与 `find_replace` 能做到「无害」，另两臂不能**
   - 中位：`noop` **0.0037** ≈ `patch` **0.0040** < `find_replace` 0.0045 < `rewrite` 0.0058 ≈ `swe_edit` 0.0062。
   - 配对检验：`patch` 与 `find_replace` 与 noop **CI 跨 0（打平）**；`rewrite` 与 `swe_edit` **显著差于 noop**。
   - 结论不是「低噪下别修」，而是 **「低噪下只有局部内容锚编辑是无害的」**。

2. **区分点在尾部，不在中心趋势**（本记录最重要的一条）

   | | 中位 | max | max/中位 |
   |---|---|---|---|
   | `find_replace` | 0.0045 | **0.0090** | 2.0× |
   | `swe_edit` | 0.0062 | **0.2579** | **41.6×** |

   - **中位只差 1.4 倍，max 差 29 倍。** `swe_edit` 的均值 0.0289 完全由一篇（破坏 3203 字符）撑起，逐篇为 `3203 106 90 67 52 46 30 21 12 10 6`。
   - 机制：`find_replace` 的 `PATTERN_NOT_FOUND`、`patch` 的 `KEY_NOT_FOUND` **给破坏设了上界**；行号是合法的位置性地址，**错的时候系统一次都拦不住**（op 失败率恒 0.0%）。
   - ⚠️ 原结论「swe_edit 行号脱靶导致 cMER 恶化至 0.0289」**作废** —— 那是均值口径的误读。正确说法是**尾部风险**，不是普遍更差。

3. **编辑粒度（blast radius）有了直接测量**
   - `edit_spans` / 磁带 op 数：`swe_edit` 145.6 / 42.3 = **3.44**；`find_replace` 38.6 / 47.4 = **0.81**。
   - 一次 `edit(start,end,text)` 平均产生 3.4 个改动区域 —— 行区间替换会连带重写未出错的内容。

4. **破坏的成分不同**
   - `swe_edit` 以 **改错**为主（broken_sub 147.6）；`rewrite` 以 **幻觉插入 + 漏抄**为主（ins 56.4 / del 32.9，del 占 35.4%）；`patch`/`find_replace` 的破坏总量小一个数量级。

5. **Token**：`patch` 383.5k，较 `rewrite` 567.5k 与 `find_replace` 589.9k **省约 33%**。但 3 个样本触发 `incomplete`（单轮补丁过长被截断）。


## 资产与备注

- 磁带：`runs/dta19-doc-1t/sessions/`（唯一权威来源，两个报告共用同一批磁带）
- 报告：`runs/dta19-doc-1t/report.json`（`noop`/`rewrite`/`swe_edit`/`find_replace`）
- **`patch-1turn` 的数字取自** `runs/dta19-doc-1t-be/report.json` —— 同一批磁带以 `apply_mode=best_effort` 重放（`--replay-with patch-1turn=patch-1turn-besteffort`）+ `--report-only`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 5 = 55 个 session。
- 观测重点：关注 rewrite 在长文本下的 broken_rate 与 halluc_rate，检验 patch 的精准片段修改收益。

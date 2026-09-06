# dta19-l1-doc-1t

> 状态：已完成（2026-09-05）

## 问题

在中等错误率德语子集（`dta19-l1`，官方基线 CMER 约 2.40%）上，整篇长文档单轮修复（平均 ~14.4k 字符 / ~4.1k BPE tokens）：
1. **跨越过修惩罚分水岭**：基准错误率从 L0（~0.4%）提升至 L1（~2.4%）后，修复带来的收益（fixed）能否首次全面压过过修（broken），使各修复 arm 相对 `noop` 取得显著正向收益？
2. **长上下文定位精度对比**：在 ~4k tokens 上下文的长文档下，`patch-1turn`、`swe_edit`、`find_replace` 与 `rewrite` 在密集瑕疵定位上的召回率与过修控制；
3. **行号脱靶检验**：检验 `swe_edit` 在中度错误率长文档单轮下，是否依然会发生 L0 阶段观测到的跨页行号漂移误删事故。

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
    --split dev --loaders dta19-l1/de/doc `
    --out runs/dta19-l1-doc-1t --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l1/de/doc \
    --out runs/dta19-l1-doc-1t --workers 11
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
| `noop` | **0.0238** | 0.0242 [0.0229, 0.0257] | 0.0279 | **0.0284** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite` | **0.0119** | 0.0122 [0.0100, 0.0151] | 0.0160 | **0.0236** | 82.35% | 0.81% | 0.53% | 326.2 | 615.6k | 91.4% |
| `patch-1turn`〔best_effort〕 | **0.0099** | 0.0112 [0.0093, 0.0139] | 0.0148 | **0.0231** | 70.97% | 0.41% | 0.24% | 235.6 | 744.0k | 93.4% |
| `swe_edit` | **0.0115** | 0.0127 [0.0102, 0.0159] | 0.0141 | **0.0279** | 70.22% | 0.54% | 0.32% | 226.0 | 663.7k | — |
| `find_replace` | **0.0095** | 0.0127 [0.0087, 0.0169] | 0.0238 | **0.0279** | 64.23% | 0.38% | 0.24% | 201.4 | 1.05M | — |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite` | 16.1 | 18.1 | 72.2 | 17.0% |
| `patch-1turn` | 9.8 | 8.5 | 27.8 | 18.5% |
| `swe_edit` | 9.0 | 12.1 | 38.8 | 20.2% |
| `find_replace` | 7.8 | 6.4 | 25.4 | 16.1% |

## 读法与结论

1. **跨过「过修分水岭」：四臂全部显著优于 noop**
   - 基线从 L0 的 0.0040 升到 **0.0242** 后，修错收益首次压过过修损失；四臂中位 0.0095~0.0119，把 noop 的 0.0238 **砍掉一半以上**，配对检验全部显著。

2. **四臂彼此统计不可分**
   - 中位：`find_replace` 0.0095 < `patch` 0.0099 < `swe_edit` 0.0115 < `rewrite` 0.0119，跨度仅 1.25 倍。
   - 配对差全部 CI 跨 0（`rewrite` vs `patch` +0.00097 [−0.00223,+0.00449]；`patch` vs `swe_edit` −0.00146 [−0.00306,+0.00003]）。
   - **只能说「均值/中位最优」，不能说「更好」。** n=11 撑不起更强的断言。

3. **原「`patch` 改不动」的结论作废**
   - 那是 `apply_mode=atomic` 的连坐所致：单条 `replace` 失配即整批回滚，本 run 作废了 **83.7%** 的已提交 op（典型：第 229 条失败 / 共 774 条 ⇒ 773 条正确修复全部丢弃）。
   - 修正为 `best_effort` 后 `fixed` 从 20.27% 升到 **70.97%**，与 `swe_edit`（70.22%）持平；cMER 中位 0.0099 为四臂最优。
   - 而 `patch` 的每-op 失败率仅 **0.24%**，是全场定位精度最好的臂。

4. **L1 几乎没有重尾**
   - 各臂均值/中位比 1.02~1.33×，max 0.0231~0.0279。与 L0-doc 的 4.68× 形成对比 —— **噪声越高，稀有灾难越不突出**（因为基线本身就差）。

5. **`patch` 在过修控制上仍最好**：broken 0.41% / halluc 0.24%，均为四臂最低，同时保住 71% 的召回 —— 「以更小的破坏拿到相当的召回」。


## 资产与备注

- 磁带：`runs/dta19-l1-doc-1t/sessions/`（唯一权威来源，两个报告共用同一批磁带）
- 报告：`runs/dta19-l1-doc-1t/report.json`（`noop`/`rewrite`/`swe_edit`/`find_replace`）
- **`patch-1turn` 的数字取自** `runs/dta19-l1-doc-1t-be/report.json` —— 同一批磁带以 `apply_mode=best_effort` 重放（`--replay-with patch-1turn=patch-1turn-besteffort`）+ `--report-only`
- 数据集规模：`dta19-l1` dev split 共 11 篇文档（同 L0 相同的 11 篇源文档与抽样页），总计 11 × 5 = 55 个 session。
- 官方参考基线：官方评测中 `dta19-l1` 的 `noop` cMER micro 为 0.0240，而参赛系统（如 blocr 0.0177、bnf-mistral 0.0054）均跑赢 noop。重点观测本实验各 tool arm 能否取得 $\Delta < 0$ 的实质改善。

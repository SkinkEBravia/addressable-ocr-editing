# dta19-l2-doc-1t

> 状态：已完成（2026-09-05）

## 问题

在高错误率重度退化德语子集（`dta19-l2`，官方基线 CMER 约 5.46%）上，整篇长文档单轮修复（平均 ~14.4k 字符 / ~4.1k BPE tokens）：
1. **重度噪声下的修复天花板**：在严重破损与生僻识别瑕疵密集的场景下，各工具配置能否展现出大幅超越 `noop` 的强纠错能力？
2. **重度噪声对各工具的鲁棒性冲击**：
   - `rewrite` 是否会因大面积词形模糊而诱发自回归自由发挥与幻觉生成？
   - `patch-1turn` 的行划分在破损排版下是否仍能稳定保持块 ID 锚定？
   - `find_replace` 在错字极多时的短语匹配是否存在多重命中歧义？
3. **收益与成本权衡**：对比各工具在重度退化文档下的字符错误修复率、Token 输出成本及抗过修稳定性。

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
    --split dev --loaders dta19-l2/de/doc `
    --out runs/dta19-l2-doc-1t --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l2/de/doc \
    --out runs/dta19-l2-doc-1t --workers 11
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
| `noop` | **0.0587** | 0.0580 [0.0549, 0.0607] | 0.0624 | **0.0659** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite` | **0.0527** | 0.0560 [0.0316, 0.0912] | 0.0624 | **0.2139** | 45.88% | 2.58% | 0.38% | 316.3 | 290.6k | — |
| `patch-1turn`〔best_effort〕 | **0.0239** | 0.0291 [0.0216, 0.0382] | 0.0564 | **0.0584** | 66.64% | 1.04% | 0.36% | 613.5 | 625.2k | — |
| `swe_edit` | **0.0194** | 0.0258 [0.0190, 0.0350] | 0.0479 | **0.0587** | 68.73% | 0.89% | 0.43% | 624.8 | 719.1k | — |
| `find_replace` | **0.0193** | 0.0276 [0.0187, 0.0376] | 0.0605 | **0.0621** | 64.54% | 0.70% | 0.28% | 429.1 | 576.5k | — |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite` | 18.0 | 349.9 | 39.9 | 85.8% |
| `patch-1turn` | 34.3 | 47.4 | 43.3 | 37.9% |
| `swe_edit` | 33.5 | 20.2 | 57.1 | 18.2% |
| `find_replace` | 29.2 | 13.4 | 28.0 | 18.9% |

## 读法与结论

1. **重噪（L2）整篇：三个编辑臂显著优于 noop 且彼此不可分**
   - 中位：`find_replace` 0.0193 ≈ `swe_edit` 0.0194 < `patch` 0.0239 ≪ `rewrite` 0.0527 < `noop` 0.0587。
   - 三个编辑臂把 noop 的 0.0587 压到三分之一，配对检验全部显著；彼此之间 CI 全部跨 0。

2. **`rewrite` 在重噪长文本下失效 —— 失败模式是「写不完」，不是「写不好」**

   | 状态 | 篇数 | cmer |
   |---|---|---|
   | `done` | 6 | 0.0187 / 0.0197 / 0.0229 / 0.0241 / 0.0262 / 0.2139 |
   | **`failed:incomplete`** | **5** | 回退原文（≈ noop） |

   - **完成的 6 篇里 5 篇落在 0.019~0.026，与最优臂持平。** 问题是 **45% 的文档根本输出不完**：L2 错误密度约 5.8%，模型既要复现 ~14.4k 字符又要密集修复，输出长度撞预算。
   - 这是「输出遍历全文」这一聚焦机制的**容量约束**。同一批文档在 `seq-local` 形态（每轮只重写一个单元）下 `rewrite_seq` 恢复到中位 0.0206 —— **切块解除了容量约束**。

3. **中心趋势与尾部指向不同的臂**（本记录最值得注意的一条）

   | arm | 中位 | max |
   |---|---|---|
   | `find_replace` | **0.0193** | 0.0621 |
   | `swe_edit` | 0.0194 | 0.0587 |
   | `patch` | 0.0239 | **0.0584** |
   | `rewrite` | 0.0527 | **0.2139** |

   - `patch` 的**中位排第三，尾部却最紧**；`rewrite` 的尾部是次高者的 3.4 倍。
   - ⇒ 报表必须**中位与 max 并列**，只看任何一个都会选错臂。

4. **单轮在 L2 的系统性输出瓶颈**：错误极多而要求一次吐完，四个 LLM 臂均出现 2~5 例截断。这直接指向 `seq` 形态 —— 把任务拆到 10 轮以化解单轮输出压力。


## 资产与备注

- 磁带：`runs/dta19-l2-doc-1t/sessions/`（唯一权威来源，两个报告共用同一批磁带）
- 报告：`runs/dta19-l2-doc-1t/report.json`（`noop`/`rewrite`/`swe_edit`/`find_replace`）
- **`patch-1turn` 的数字取自** `runs/dta19-l2-doc-1t-be/report.json` —— 同一批磁带以 `apply_mode=best_effort` 重放（`--replay-with patch-1turn=patch-1turn-besteffort`）+ `--report-only`
- ⚠️ `runs/dta19-l2-doc-1t-be` 的 **`rewrite` 栏不可用** —— replay 重 fold 了全部臂，5 个 `failed:incomplete` 会话的回退语义丢失，cmer 被抬到 1.0。见 [[shit#13. `--replay` 会重 fold 全部臂，且毁掉失败会话]]
- 数据集规模：`dta19-l2` dev split 共 11 篇文档（同 L0/L1 相同的 11 篇源文档与抽样页），总计 11 × 5 = 55 个 session。
- 官方参考基线：官方评测中 `dta19-l2` 的 `noop` cMER micro 为 0.0546，blocr 达到 0.0338，bnf-mistral 达到 0.0082。

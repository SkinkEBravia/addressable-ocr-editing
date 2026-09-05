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
| patch-1turn | 整篇块 id 补丁 | 单轮行划分 patch（约 300~400 行）；**apply_mode=atomic（默认）**，未隐去任何操作 —— 记录初版误写为 best_effort，见下方「配置更正」 |
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

### best_effort 重放结果（2026-09-06，零 API 成本）

| patch-1turn 配置 | cmer ↓ [95% CI] | fixed ↑ | broken ↓ | halluc ↓ |
|---|---|---|---|---|
| `atomic`（原记录） | 0.0461 [0.0361, 0.0549] | 30.32% | 0.67% | 0.18% |
| **`best_effort`（修正）** | **0.0291 [0.0216, 0.0382]** | **66.64%** | 1.04% | 0.36% |
| 变化 | **−36.9%** | **2.20×** | 1.55× | 2.0× |

修正后的 l2 全臂（noop 0.0580）：

| arm | cmer | fixed | broken | halluc | 备注 |
|---|---|---|---|---|---|
| swe_edit | **0.0258** | 68.73% | 0.89% | 0.43% | |
| find_replace | 0.0276 | 64.54% | 0.70% | 0.28% | |
| **patch (best_effort)** | 0.0291 | 66.64% | 1.04% | 0.36% | |
| rewrite | 0.0560 | 45.88% | 2.58% | 0.38% | **5/11 `failed:incomplete`** |
| noop | 0.0580 | — | — | — | |

配对检验（三个编辑臂，best_effort 版报告内）：

| 对比 | Δcmer [95% CI] | 判定 |
|---|---|---|
| noop vs patch | +0.02886 [+0.01921, +0.03757] | **显著优于 noop** |
| noop vs swe_edit | +0.03217 [+0.02106, +0.04073] | **显著优于 noop** |
| noop vs find_replace | +0.03034 [+0.02062, +0.03945] | **显著优于 noop** |
| patch vs swe_edit | +0.00331 [−0.00907, +0.01611] | CI 跨 0 |
| patch vs find_replace | +0.00147 [−0.01289, +0.01473] | CI 跨 0 |
| swe_edit vs find_replace | −0.00184 [−0.01607, +0.01266] | CI 跨 0 |

⇒ **三个编辑臂在 l2 统计上完全不可分，且全部显著优于 noop。**

### `rewrite` 在 l2 的失败模式：写不完，不是写不好

| 状态 | 篇数 | cmer |
|---|---|---|
| `done` | 6 | 0.0187 / 0.0197 / 0.0229 / 0.0241 / 0.0262 / 0.2139 |
| **`failed:incomplete`** | **5** | 回退原文（≈ noop） |

**完成的 6 篇里有 5 篇落在 0.019~0.026，与最优臂持平。** 也就是说 rewrite 在 l2 的问题不是质量，
是 **45% 的文档根本输出不完** —— l2 错误密度约 5.8%，模型既要复现全部 ~14.4k 字符又要密集修复，
输出长度撞上预算。

> **这是「输出遍历全文」这一聚焦机制的容量约束**，见 `plan/experiment-batch-2-anchors.md` §1.1。
> 高噪 + 长文档下，全文重写不是变差，是**不可行**。

> [!danger] replay 副作用：本 run 的 `-be` 报告中 `rewrite` 数字不可用
> `--replay` 会重 fold **所有**臂（不只被 `--replay-with` 覆盖的那个）。对 5 个
> `failed:incomplete` 的 rewrite 会话，原始 run 的 `session.output` 回退为原文（cmer ≈ noop），
> 但 replay 重 fold 时 `extract` 在空 tool_state 上返回空串且**不抛异常** ⇒ 未走
> `except: output = task.input` 的回退分支 ⇒ cmer 变成 **1.0000**，rewrite 聚合从 0.0560 被抬到 0.4841。
>
> **本节 rewrite 的数字取自原始报告 `runs/dta19-l2-doc-1t/report.json`；`-be` 报告仅 `patch-1turn` 可用。**
> 其余三个已重放的 run（l0 chunk / l0 doc / l1 doc）经逐样本核对，非 patch 臂**零改动**，不受此影响。

资产：`runs/dta19-l2-doc-1t-be/report.json`（replay `changed=10 lower_bound=0`）


## 结果

| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | 0.0580 [0.0549, 0.0607] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| rewrite | 0.0560 [0.0316, 0.0912] | -0.0020 [-0.0257, +0.0317] | 45.88% | 54.12% | 2.58% | 0.38% | 290.6k | — |
| patch-1turn | 0.0461 [0.0361, 0.0549] | -0.0118 [-0.0233, -0.0023] | 30.32% | 69.68% | **0.67%** | **0.18%** | 625.2k | — |
| swe_edit | **0.0258** [0.0190, 0.0350] | **-0.0322** [-0.0407, -0.0211] | **68.73%** | **31.27%** | 0.89% | 0.43% | 719.1k | — |
| find_replace | 0.0276 [0.0187, 0.0376] | -0.0303 [-0.0394, -0.0206] | 64.54% | 35.46% | 0.70% | 0.28% | 576.5k | — |

*注：长文档单轮在严重退化（L2）下输出压力显著增大，触发 incomplete 截断数分别为：`rewrite` (5/11), `patch-1turn` (2/11), `swe_edit` (2/11), `find_replace` (2/11)。*

配对差异（cMER Δ，[95% CI]）：
- `swe_edit vs noop`：Δ = -0.0322 [-0.0407, -0.0211]（swe_edit 显著大胜 noop，错误率降低超 55%）
- `find_replace vs noop`：Δ = -0.0303 [-0.0394, -0.0206]（find_replace 显著大胜 noop）
- `swe_edit vs find_replace`：Δ = -0.0018 [-0.0161, +0.0127]（两者统计平手）
- `swe_edit vs rewrite`：Δ = -0.0302 [-0.0678, -0.0003]（swe_edit 显著优于 rewrite）
- `find_replace vs rewrite`：Δ = -0.0284 [-0.0561, -0.0087]（find_replace 显著优于 rewrite）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | 0.0585 | 0.0580 | 0.2962 | +0.0000 |
| swe_edit | **0.0246** | **0.0258** | **0.1244** | **+0.8182** |
| find_replace | 0.0355 | 0.0276 | 0.1375 | **+0.8182** |
| patch-1turn | 0.0483 | 0.0461 | 0.2465 | +0.3636 |
| rewrite | 0.0675 | 0.0560 | 0.1954 | +0.3636 |

## 读法与结论

1. **局部编辑工具（swe_edit 与 find_replace）大放异彩**：
   - 在基准错误率高达 ~5.8% 的 L2 环境下，`swe_edit` 和 `find_replace` 将 cMER 从 0.0580 腰斩至 **0.0258~0.0276**（官方 Micro cMER 低至 0.0246），修错率达到 64%~69%，Preference 达到 +0.8182；
   - 证明在重度噪点下，显式编辑指令能够精准狙击密集瑕疵，且不会破坏未修改的主干上下文。
2. **`rewrite` 在重噪长文本下单轮彻底崩盘**：
   - `rewrite` 遭遇了高达 5/11（近半数）的 `incomplete` 截断，Micro cMER 甚至逆向劣化到 0.0675；
   - 其过修率飙升至 2.58%，CI 方差剧烈扩散（[0.0316, 0.0912]）。严重噪声诱发了自回归模型严重的幻觉性重写和长尾文本膨胀。
3. **单轮模式在 L2 下的系统性输出瓶颈**：
   - 由于整篇文档错误极多，单轮要求一次性吐出所有修改，导致所有 LLM arm 均出现了 2~5 例截断。这直接呼唤流式连续输入（`seq-local`）通过将任务拆解到 10 轮中来化解单轮输出压力。

## 资产与备注

- 报告：`runs/dta19-l2-doc-1t/report.json`；磁带：`runs/dta19-l2-doc-1t/sessions/`
- 数据集规模：`dta19-l2` dev split 共 11 篇文档（同 L0/L1 相同的 11 篇源文档与抽样页），总计 11 × 5 = 55 个 session。
- 官方参考基线：官方评测中 `dta19-l2` 的 `noop` cMER micro 为 0.0546，blocr 达到 0.0338，bnf-mistral 达到 0.0082。

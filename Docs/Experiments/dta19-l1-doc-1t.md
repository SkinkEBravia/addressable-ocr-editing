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
| patch-1turn | 整篇块 id 补丁 | 单轮行划分 patch（约 300~400 行）；**apply_mode=atomic（默认）**，未隐去任何操作 —— 记录初版误写为 best_effort，见下方「配置更正」 |
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

| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | 0.0242 [0.0229, 0.0257] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| rewrite | **0.0122** [0.0100, 0.0151] | **-0.0120** [-0.0152, -0.0080] | **82.35%** | **17.65%** | 0.81% | 0.53% | 615.6k | 91.4% |
| patch-1turn | 0.0209 [0.0171, 0.0243] | -0.0034 [-0.0069, -0.0007] | 20.27% | 79.73% | **0.15%** | **0.08%** | 744.0k | 93.4% |
| swe_edit | 0.0127 [0.0102, 0.0159] | -0.0115 [-0.0144, -0.0085] | 70.22% | 29.78% | 0.54% | 0.32% | 663.7k | — |
| find_replace | 0.0127 [0.0087, 0.0169] | -0.0116 [-0.0155, -0.0076] | 64.23% | 35.77% | 0.38% | 0.24% | 1.0M | — |

*注：`swe_edit` 与 `find_replace` 各有 1 个 session 触发 `incomplete`，有效统计样本为 10/11。*

配对差异（cMER Δ，[95% CI]）：
- `rewrite vs swe_edit`：Δ = -0.0005 [-0.0039, +0.0029]（两者统计平手）
- `rewrite vs find_replace`：Δ = -0.0005 [-0.0054, +0.0042]（两者统计平手）
- `swe_edit vs find_replace`：Δ = +0.0000 [-0.0034, +0.0027]（两者统计绝对平手）
- `rewrite vs patch-1turn`：Δ = -0.0087 [-0.0129, -0.0038]（rewrite 显著优于 patch-1turn）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | 0.0249 | 0.0242 | 0.1601 | +0.0000 |
| rewrite | **0.0121** | **0.0122** | **0.0515** | +0.8182 |
| swe_edit | 0.0152 | 0.0127 | 0.0724 | **+0.9091** |
| find_replace | 0.0148 | 0.0127 | 0.0704 | +0.8182 |
| patch-1turn | 0.0229 | 0.0209 | 0.1362 | +0.2727 |

## 修正：atomic 连坐与 best_effort 重放（2026-09-06）

`patch-1turn` 实际以 `apply_mode=atomic` 运行（见上方配置更正）。磁带实测：

| | 提交 op | 每-op 失败率 | 因 atomic 作废的 op |
|---|---|---|---|
| `dta19-l1-doc-1t` | 3339 | **0.24%** | **83.7%** |

典型：`第 229 条失败 / 共 774 条` ⇒ 773 条正确修复全部作废。
失败**全部**是 `PATTERN_NOT_FOUND`（`old` 不匹配），**零条 `KEY_NOT_FOUND`、零条解析错误** ——
块 id 从未写错，patch 的单条定位精度实为全场最好。

### best_effort 重放结果（零 API 成本）

`apply_mode` 不是 `patch_clause()` 的入参、不进提示词 ⇒ 模型响应逐字不变，仅工具 fold 改变，
因此可用磁带重放（`configs/toolsets/patch-1turn-besteffort.toml`，与 `patch-1turn.toml` 仅
`apply_mode` 一行之差）：

```powershell
uv run python -m experiment --out runs/dta19-l1-doc-1t-be --replay `
    --replay-with patch-1turn=patch-1turn-besteffort
uv run python -m experiment --out runs/dta19-l1-doc-1t-be --report-only   # replay 不重算分数，必须补这步
```

| patch-1turn 配置 | cmer ↓ [95% CI] | fixed ↑ | broken ↓ | halluc ↓ |
|---|---|---|---|---|
| `atomic`（原记录） | 0.0209 [0.0171, 0.0243] | 20.27% | **0.15%** | **0.08%** |
| **`best_effort`（修正）** | **0.0112 [0.0093, 0.0139]** | **70.97%** | 0.41% | 0.24% |
| 变化 | **−46.4%** | **3.50×** | 2.73× | 3.0× |

修正后的全臂排序（cmer 均值）：

| arm | cmer | fixed | broken | halluc |
|---|---|---|---|---|
| **patch-1turn (best_effort)** | **0.0112** | 70.97% | 0.41% | 0.24% |
| rewrite | 0.0122 | 82.35% | 0.81% | 0.53% |
| swe_edit | 0.0127 | 70.22% | 0.54% | 0.32% |
| find_replace | 0.0127 | 64.23% | 0.38% | 0.24% |
| noop | 0.0242 | — | — | — |

**配对检验（best_effort 版报告内）**：

| 对比 | Δcmer [95% CI] | 判定 |
|---|---|---|
| noop vs 四臂 | 均 +0.0116~+0.0130，CI 不含 0 | **四臂全部显著优于 noop** |
| rewrite vs patch | +0.00097 [−0.00223, +0.00449] | CI 跨 0 |
| patch vs swe_edit | −0.00146 [−0.00306, +0.00003] | CI 跨 0（几乎触界） |
| patch vs find_replace | −0.00143 [−0.00460, +0.00140] | CI 跨 0 |

> [!warning] 措辞纪律
> 四臂**彼此全部 CI 跨 0**。只能说 **"patch 从显著垫底恢复到与其余三臂统计持平、均值最优"**，
> **不能**说"翻到第一"。n=11 撑不起更强的断言。

### 对原结论的影响

原「读法与结论」第 3 条（`patch-1turn` 在密集错误下"倾向于改不动"、"局部局限性"）**作废** ——
20.27% 的召回不是操作逻辑的性质，是 atomic 连坐把 83.7% 的正确 op 作废的结果。
修正后 patch 的召回为 70.97%，与 swe_edit（70.22%）持平。

真正成立的是：**patch 在同等召回下的 broken（0.41%）与 halluc（0.24%）均为四臂最低**，
即"以更小的破坏拿到相当的召回"。

## 读法与结论

1. **全面跨越“过修分水岭”：所有修复 arm 全线战胜 noop**：
   - 在基准错误率提升至 2.42% 的 L1 环境下，模型修错（fixed）收益终于远大于过修（broken）损失；
   - `rewrite`、`swe_edit`、`find_replace` 三者均将 cMER 从 0.0242 砍半压制到 **0.0122~0.0127**（Δ vs noop 高达 -0.0115~-0.0120，官方 Preference Score 达到 +0.82~+0.91），完全复现了官方竞赛中所有模型在 L1 全面反超 noop 的学术结论。
2. **`rewrite` 与编辑工具在此退化级并驾齐驱**：
   - `rewrite` 达到全场最高的修错召回率（82.35%），其过修率（0.81%）在 2.4% 基准错误下被完全吸收；
   - `find_replace` 与 `swe_edit` 在微调精准度上表现优异，过修率更低（0.38% 与 0.54%），且 cMER 与 rewrite 统计学完全平手（Δ = -0.0005，CI 跨 0）。
3. **`patch-1turn` 在密集错误下的局部局限性**：
   - patch-1turn 的保真度依然惊人（broken 仅 0.15%，halluc 仅 0.08%），但其修错召回率仅 20.27%，说明单轮按块提交补丁在长文档密集错字场景下倾向于“改不动”（漏修 missed 高达 79.73%），导致 cMER 改善幅度（0.0209）不如其他工具。

## 资产与备注

- 报告：`runs/dta19-l1-doc-1t/report.json`；磁带：`runs/dta19-l1-doc-1t/sessions/`
- 数据集规模：`dta19-l1` dev split 共 11 篇文档（同 L0 相同的 11 篇源文档与抽样页），总计 11 × 5 = 55 个 session。
- 官方参考基线：官方评测中 `dta19-l1` 的 `noop` cMER micro 为 0.0240，而参赛系统（如 blocr 0.0177、bnf-mistral 0.0054）均跑赢 noop。重点观测本实验各 tool arm 能否取得 $\Delta < 0$ 的实质改善。

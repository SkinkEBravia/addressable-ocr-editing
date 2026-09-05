# dta19-chunk-1t

> 状态：已完成（2026-09-04）

## 问题

在极端低错误率德语子集（`dta19-l0`，基线 CMER 约 0.36%）上，按单 chunk 独立 session、单轮修复：
1. 各主流工具配置（noop, rewrite, patch-1turn, swe_edit, find_replace）对低错误文本的修复效能如何？
2. 在高保真文本上，各工具能否有效避免过修（broken_rate）与模型主动新增幻觉（halluc_rate）？
3. 行号锚（swe_edit）与字符串锚（find_replace）在小上下文单轮下的表现与 patch 对比如何？

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite | 单轮重写 | 每个 chunk 一次性完整重写；JSON 条款 |
| patch-1turn | 块 id 锚补丁 | 单轮行划分 patch；**apply_mode=atomic（默认）**，未隐去任何操作 —— 记录初版误写为 best_effort，见下方「配置更正」 |
| swe_edit | 行号锚编辑 | 单轮行号区间替换（edit start:end "text"） |
| find_replace | 字符串锚替换 | 单轮字面字符串匹配替换（find_replace "old" "new"） |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/chunk `
    --out runs/dta19-chunk-1t --workers 32
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/chunk \
    --out runs/dta19-chunk-1t --workers 32
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

atomic 下本 run 提交 1024 个 op，每-op 失败率 **1.27%**，因连坐作废 **19.5%**。重放后：

| patch-1turn 配置 | cmer ↓ [95% CI] | fixed ↑ | broken ↓ | halluc ↓ |
|---|---|---|---|---|
| `atomic`（原记录） | 0.0076 [0.0064, 0.0090] | 31.75% | 0.51% | 0.39% |
| `best_effort`（修正） | **0.0079 [0.0067, 0.0093]** | 36.21% | 0.56% | 0.42% |

**与 l0 doc-1t 同向：best_effort 反而略差。** 修复量上升（31.75% → 36.21%）的收益抵不过破坏上升
（0.51% → 0.56%）的代价 —— 在错误率仅 0.4% 的文本上，"少做事"本身就是优势。

修正后 l0 chunk 的配对检验（best_effort 版报告内）：

| 对比 | Δcmer [95% CI] | 判定 |
|---|---|---|
| noop vs rewrite | −0.00872 [−0.01664, −0.00362] | **rewrite 显著差于 noop** |
| noop vs swe_edit | −0.00493 [−0.00652, −0.00341] | **显著差于 noop** |
| noop vs patch | −0.00399 [−0.00532, −0.00287] | **显著差于 noop** |
| noop vs find_replace | −0.00305 [−0.00448, −0.00173] | **显著差于 noop** |
| rewrite vs find_replace | +0.00567 [+0.00088, +0.01339] | find_replace 显著更优 |
| swe_edit vs find_replace | +0.00188 [+0.00042, +0.00347] | find_replace 显著更优 |
| patch vs swe_edit | −0.00095 [−0.00216, +0.00021] | CI 跨 0 |
| patch vs find_replace | +0.00093 [−0.00020, +0.00199] | CI 跨 0 |

> **与 doc 形态的差别**：l0 **doc** 上 patch/find_replace 与 noop 打平；l0 **chunk** 上四臂
> **全部显著差于 noop**。孤立小块缺少跨块上下文，误判更多 —— 低噪场景下切块是有害的。

资产：`runs/dta19-chunk-1t-be/report.json`（replay `changed=11 lower_bound=0`）


## 结果

| arm | cmer ↓ [95% CI] | Δ noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | **0.0040** [0.0032, 0.0049] | — | 0.00% | 91.82% | **0.00%** | **0.00%** | **0** | — |
| rewrite | 0.0127 [0.0076, 0.0209] | +0.0087 [+0.0036, +0.0166] | 39.04% | 52.78% | 1.06% | 0.49% | 2.5M | 97.5% |
| patch-1turn | 0.0076 [0.0064, 0.0090] | +0.0036 [+0.0026, +0.0050] | 31.75% | 60.06% | 0.51% | 0.39% | 2.5M | 99.4% |
| swe_edit | 0.0089 [0.0073, 0.0106] | +0.0049 [+0.0034, +0.0065] | 33.63% | 58.19% | 0.65% | 0.47% | 2.3M | 99.1% |
| find_replace | 0.0070 [0.0056, 0.0086] | +0.0031 [+0.0017, +0.0045] | **39.31%** | **52.51%** | 0.48% | 0.37% | 2.2M | 99.4% |

配对差异（cMER Δ，[95% CI]）：
- `find_replace vs patch-1turn`：Δ = -0.0006 [-0.0017, +0.0006]（统计平手）
- `patch-1turn vs swe_edit`：Δ = -0.0013 [-0.0025, -0.0002]（patch 显著优于 swe_edit）
- `find_replace vs swe_edit`：Δ = -0.0019 [-0.0035, -0.0004]（find_replace 显著优于 swe_edit）
- `find_replace vs rewrite`：Δ = -0.0057 [-0.0134, -0.0009]（find_replace 显著优于 rewrite）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | **0.0036** | **0.0040** | **0.0219** | **0.0000** |
| find_replace | 0.0082 | 0.0070 | 0.0291 | -0.2636 |
| patch-1turn | 0.0068 | 0.0076 | 0.0412 | -0.5000 |
| swe_edit | 0.0087 | 0.0089 | 0.0380 | -0.5000 |
| rewrite | 0.0236 | 0.0127 | 0.0342 | -0.3818 |

## 读法与结论

1. **全面印证官方竞赛与论文结论：低噪（L0）下“越修越差”，全部 arm 不敌 noop**：
   - 在基线错误率仅 ~0.36% 的 `dta19-l0` 上，`noop` 以 cMER 0.0040 毫无悬念胜出，所有通过 LLM 修复的 arm 均呈现不同程度的劣化（Δ vs noop 均为显著正值，Pref Score 均为负值）。这与 HIPE 官方评测中除 BnF run2 以外所有系统均大幅跑输 `noop` 的结论完全吻合。
2. **细粒度分解揭示“过修惩罚”机理**：
   - 模型并非没有纠错能力：各 arm 均修对了 31%~39% 的真实错误（fixed_rate）。
   - 但在极致低噪环境下，容错空间几乎为零。只要模型在 1,000 字中引入 0.5%~1.0% 的过修（broken_rate）或插入幻觉（halluc_ins），改坏的原有正确字符数量就直接抹平甚至翻倍超过了修对的收益，导致总错误率急剧上升。
3. **工具形态 vs 全文重写：局部编辑能有效抑制过修幅度**：
   - `rewrite` 劣化最为严重（cMER 0.0127，broken_rate 高达 1.06%，Micro-cMER 飙至 0.0236），整段自回归重写缺乏锚点约束，模型易无意识对非目标区域进行现代化平滑与微调；
   - `find_replace`（0.0070）与 `patch-1turn`（0.0076）表现明显好于 rewrite，其过修率（0.48%、0.51%）仅为 rewrite 的一半左右，证明局部定位锚点能显著保护无错误文本；
   - `swe_edit`（0.0089）在单轮无编译器反馈场景下，因偶发行号对齐偏差，效果弱于字符串锚与块 patch。
4. **Token 开销特征**：
   - DeepSeek-V4-Flash 的 reasoning 占比极高（97.5% ~ 99.4%），思考开销吃掉了绝大多数 token（各 arm 总计消耗 2.2M~2.5M tokens）。在单轮 chunk 任务下，工具之间没有显著的 token 节省优势。

## 资产与备注

- 报告：`runs/dta19-chunk-1t/report.json`；磁带：`runs/dta19-chunk-1t/sessions/`
- 数据集规模：`dta19-l0` dev split 共 110 个 chunk，总计 110 × 5 = 550 个 session。
- 任务独立，支持高并发快速跑完（推荐 32 workers）。

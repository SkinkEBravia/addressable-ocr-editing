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
| patch-1turn | 块 id 锚补丁 | 单轮行划分 patch；**apply_mode=best_effort**，未隐去任何操作（全部七个 SurfaceOp）。原以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，已用磁带重放修正 —— 见 [[pitfalls#11. 实验记录里的配置描述与 toml 不符]] |
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

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[pitfalls#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0030** | 0.0040 [0.0032, 0.0049] | 0.0074 | **0.0333** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite` | **0.0057** | 0.0127 [0.0076, 0.0209] | 0.0226 | **0.3634** | 39.04% | 1.06% | 0.49% | 7.7 | 2.51M | 97.5% |
| `patch-1turn`〔best_effort〕 | **0.0063** | 0.0079 [0.0067, 0.0093] | 0.0168 | **0.0382** | 36.21% | 0.56% | 0.42% | 6.3 | 2.53M | 99.4% |
| `swe_edit` | **0.0059** | 0.0089 [0.0073, 0.0106] | 0.0194 | **0.0467** | 33.63% | 0.65% | 0.47% | 6.1 | 2.32M | 99.1% |
| `find_replace` | **0.0045** | 0.0070 [0.0056, 0.0086] | 0.0169 | **0.0355** | 39.31% | 0.48% | 0.37% | 5.6 | 2.24M | 99.4% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite` | 0.9 | 18.8 | 10.4 | 62.4% |
| `patch-1turn` | 0.8 | 0.5 | 5.5 | 7.5% |
| `swe_edit` | 0.9 | 0.8 | 7.5 | 8.4% |
| `find_replace` | 0.7 | 0.5 | 7.5 | 5.7% |

## 读法与结论

1. **低噪（L0）+ 孤立块：四臂全部不敌 noop，中位口径下依然如此**
   - `noop` 中位 **0.0030**，四个修复臂 0.0045~0.0063，无一例外劣化；配对检验四臂**全部显著差于 noop**。
   - 模型并非不会改：各臂修对了 33.6%~39.3% 的真实错误。但 L0 的容错空间近乎为零 —— 0.48%~1.06% 的过修就足以抹平收益。

2. **中位口径下四臂彼此接近，均值排序是重尾造成的**
   - 中位：`find_replace` 0.0045 < `swe_edit` 0.0059 < `patch` 0.0063，跨度仅 1.4 倍。
   - 但 `rewrite` 均值 0.0127 / 中位 0.0057（**2.21×**），由单个 max **0.3634** 的样本撑起。若只看均值会误判 rewrite「劣化最严重」——它的**典型表现与其他臂同量级，问题在尾部**。

3. **切块加剧误判：同为 L0，chunk 比 doc 更差**
   - chunk 下四臂全部显著差于 noop；doc 下 `patch`（中位 0.0040）与 `find_replace`（0.0045）能与 noop（0.0037）**打平**。
   - 孤立块缺少跨块上下文，模型更容易把正确文本误判为错误。

4. **Token**：reasoning 占 97.5%~99.4%，各臂共 2.2M~2.5M。单轮 chunk 下工具间**无显著 token 节省**——可见输出的压缩优势被思考开销吞掉。


## 资产与备注

- 磁带：`runs/dta19-chunk-1t/sessions/`（唯一权威来源，两个报告共用同一批磁带）
- 报告：`runs/dta19-chunk-1t/report.json`（`noop`/`rewrite`/`swe_edit`/`find_replace`）
- **`patch-1turn` 的数字取自** `runs/dta19-chunk-1t-be/report.json` —— 同一批磁带以 `apply_mode=best_effort` 重放（`--replay-with patch-1turn=patch-1turn-besteffort`）+ `--report-only`
- 数据集规模：`dta19-l0` dev split 共 110 个 chunk，总计 110 × 5 = 550 个 session。
- 任务独立，支持高并发快速跑完（推荐 32 workers）。

# dta19-chunk-1t

> 状态：待跑

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
| patch-1turn | 块 id 锚补丁 | 单轮行划分 patch；best_effort + 隐去 append/merge |
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

## 结果

| arm | cmer ↓ [95% CI] | Δ noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | 待跑 | — | 0.0% | 100.0% | 0.0% | 0.0% | 0 | — |
| rewrite | 待跑 | | | | | | | |
| patch-1turn | 待跑 | | | | | | | |
| swe_edit | 待跑 | | | | | | | |
| find_replace | 待跑 | | | | | | | |

## 读法与结论

（待实验运行后补充）

## 资产与备注

- 报告：`runs/dta19-chunk-1t/report.json`；磁带：`runs/dta19-chunk-1t/sessions/`
- 数据集规模：`dta19-l0` dev split 共 110 个 chunk，总计 110 × 5 = 550 个 session。
- 任务独立，支持高并发快速跑完（推荐 32 workers）。

# dta19-doc-1t

> 状态：待跑

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
| patch-1turn | 整篇块 id 补丁 | 单轮行划分 patch（约 300~400 行）；best_effort + 隐去 append/merge |
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

- 报告：`runs/dta19-doc-1t/report.json`；磁带：`runs/dta19-doc-1t/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 5 = 55 个 session。
- 观测重点：关注 rewrite 在长文本下的 broken_rate 与 halluc_rate，检验 patch 的精准片段修改收益。

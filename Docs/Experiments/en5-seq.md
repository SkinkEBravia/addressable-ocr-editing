# en5-seq

> 状态：已完成（2026-09-03）

## 问题

multiturn chunked doc：一文档一场对话，逐 chunk 呈现（11 轮 = 11 chunk），每 chunk 一次机会、无反馈。共享上下文（前文修复记录可见）对各 arm 是助力还是干扰？

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite_seq | 顺序重写 | 每轮呈现一个 chunk，模型回该 chunk 重写文本；无反馈 |
| patch_seq | 顺序补丁 | 每轮呈现一个 chunk 的标注视图（块 id 每 chunk 重排）；无反馈；best_effort + 隐去 append/merge |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite_seq,patch_seq --model volc-deepseek-v4-flash `
    --split dev --loaders icdar2017/en/doc `
    --ids "icdar2017/periodical__eng_periodical-5" `
    --out runs/en5-seq --workers 3
```

### bash（容器内）

```bash
docker run --rm --env-file .env \
  -v $PWD/src:/app/src -v $PWD/configs:/app/configs \
  -v $PWD/datasets:/app/datasets -v $PWD/runs:/app/runs \
  bdpc-exp uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_seq,patch_seq --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/en5-seq --workers 3
```

## 结果

| arm | status | cmer ↓ | tokens in/out | reasoning 占比 |
|---|---|---|---|---|
| noop | done | 0.0928 | 0 / 0 | — |
| rewrite_seq | done（11 轮） | 0.0551 | 88.5k / 129.6k | 91.6% |
| patch_seq | done（11 轮） | 0.0325 | 61.9k / 186.5k | 96.2% |

patch_seq 11 轮 patch 全部解析成功，共 432 个 op。

## 读法与结论

- **patch_seq 全场最佳（0.0325)**；patch 是唯一从多轮顺序形态获益的工具集（doc 单轮 0.0346 → seq 0.0325）——小块专注 + 前文修复记录可参考。
- rewrite 反而退化（doc 单轮 0.0473 → seq 0.0551)：累积上下文对 rewrite 是干扰（逐 chunk 的 JSON 约束在长对话里漂移）。
- 结论：**工具集 × 形态有交互作用**；顺序形态利好 patch，不利 rewrite。
- 成本：seq 比单轮 doc 贵约 3 倍（上下文逐轮累积，input 暴涨）——效果最好但最贵。

## 资产与备注

- 报告：`runs/en5-seq/report.json`；磁带：`runs/en5-seq/sessions/`
- 轮数 == chunk 数（11）；无反馈口径下 patch 失败是静默的（该 chunk 保留原文），分析走 replay 重 fold。
- n=1 篇文档，doc/seq 级无 CI；结论外推前需扩样。

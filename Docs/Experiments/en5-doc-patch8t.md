# en5-doc-patch8t

> 状态：待跑

## 问题

多轮 patch 整篇 doc（带反馈，8 轮预算）：给足反馈轮后 patch 的真实能力上限是多少？多少轮收敛？产出 cmer × 轮数 与 token × 轮数 曲线。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| patch | 块 id 锚补丁，多轮反馈 | 错误反馈回灌对话，最多 8 轮；atomic 应用（默认） |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,patch --model volc-deepseek-v4-flash `
    --split dev --loaders icdar2017/en/doc `
    --ids "icdar2017/periodical__eng_periodical-5" `
    --out runs/en5-doc-patch8t --workers 2
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/en5-doc-patch8t --workers 2
```

## 结果

（跑完填）

## 读法与结论

（跑完填）

## 资产与备注

- 报告：`runs/en5-doc-patch8t/report.json`；磁带：`runs/en5-doc-patch8t/sessions/`
- 与实验矩阵统一模型配置（volc-deepseek-v4-flash，默认 effort）；前代 -low 版本（en5-doc-volc-v2，patch 8 轮 0.0369）已删除，勿引用。
- 逐轮落盘：跑完后按轮 reconstruct + 评分可得 cmer/token × 轮数曲线。

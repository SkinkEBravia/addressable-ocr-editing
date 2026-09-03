# en5-doc-patch8t

> 状态：已完成（2026-09-04）

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

| arm | status | cmer ↓ | Δ vs noop | out tokens | reasoning 占比 |
|---|---|---|---|---|---|
| noop | done | 0.0928 | — | 0 | — |
| patch | **done（1 轮！）** | **0.0312** | **-0.0616** | 67.9k | 90.0% |

**cmer × 轮数**：turn 0 基线 0.0928 → **第 1 轮一把 368 条 replace 全部原子生效（11 块全更新）+ 末尾 done() 收工，0.0312**。8 轮预算只用了 1 轮。

## 读法与结论

- **patch 多轮形态在 doc 粒度拿到全场最佳（0.0312）**，且一轮收敛——块 id 锚的 replace 精度 + 标注视图 + 受影响块重渲染反馈，使模型能一次性写对 368 条 op。
- 本轮同时吃到了三个修复的红利：带引号 id 不再被拒（方言容错）、max_output_tokens 下发（368 op 的大响应不被截断）、末尾 done() 合法（一轮收束，不再整段拒绝）。
- 三锚点多轮对比（同文档、同预算）：**patch 0.0312 / 67.9k（1 轮）< swe_edit 0.0353 / 71.9k（3 轮）< find_replace 0.0362 / 163.6k（8 轮）**——块 id 锚质量与成本双优。
- 历史对照：单发 patch（best_effort）0.0346、patch_seq 0.0325 / 186k——多轮 patch 用 1/3 不到的 token 刷新了最好成绩。

## 资产与备注

- 报告：`runs/en5-doc-patch8t/report.json`；磁带：`runs/en5-doc-patch8t/sessions/`
- 与实验矩阵统一模型配置（volc-deepseek-v4-flash，默认 effort）。
- 前代 -low 版本（en5-doc-volc-v2，patch 8 轮 0.0369）已删除，勿引用。

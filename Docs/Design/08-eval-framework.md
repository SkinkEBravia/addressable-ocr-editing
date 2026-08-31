# 测评框架：BLOCR vs BLOCR+system

> 前置：本系统全部设计文档；外部资料 `related_source/`（HIPE-OCRepair-2026，只读，不得修改）。

## 目的

在同一 LLM、同一数据上比较两种 OCR 后修复方式的 **token 效率**与**修复性能**。两臂共用 BLOCR 的修复指令体，仅输出通道不同：

```text
blocr        : 原文 -> LLM -> 修复后全文（BLOCR 原样的完全重写通道）
blocr+system : 原文 -> 本系统 ingest/view -> LLM 产出 fn patch -> 写回
control-noop : 原样输出（不调 LLM，锚点对照）
```

臂位按 unit / doc 两粒度展开，见「臂位」节。

## 合理性边界（先读）

本测评与比赛目标存在错配，结论解释必须带上以下限定：

1. 比赛单元粒度小（中位 500–1200 字符）；本系统的目标场景是**大文件 + 稀疏错误**。单元轨结果不代表目标场景，故设双轨。
2. cMER 评分前的归一化抹除换行/标点差异；本系统的字节级保真优势**不计分**。比较维度只有 token 效率与 cMER。
3. BLOCR 的逐字 prompt 已从其仓库取得（见「提示词」节），两臂的差异被压缩到只剩输出通道。
4. no-correction 基线很强（存在越修越差的参赛系统），control-noop 是必设锚点。

## 数据

### 轨

| 轨 | 内容 | 口径 |
|---|---|---|
| `track-unit` | 官方转写单元，逐单元修复 | 与官方可比 |
| `track-doc` | **impresso-nzz 原生整页**（train 中位 9528 字符，test 中位 12104；GT 完整），整页修复 | 自设场景，不与官方排名可比 |

> 修订记录：原定义为"同一 `document_id` 拼接"。实测比赛数据**每文档只有一个单元**（全子集），拼接规则永不生效，故改为 nzz 原生整页。icdar2017 上的一次空转运行同时给出噪声量级：同文本同模型两遍运行，配对 output_ratio 中位从 1.04 摆动到 1.42——单元粒度的 token 比较被推理 token 噪声淹没，无结论价值。

### 集

- 迭代用 dev（GT 完整）；出数用官方已释放的 unmasked test（`data/v0.9/**/test_*.jsonl` 与 eval 仓库 `data/reference/`）。
- 语言：de / en / fr 全量；子集选择对两臂一致。

### 样本

```text
Sample = { sample_id, track, language, source_subset, ocr_text, gold_text, metadata }
```

从 jsonl 行装载；`track-doc` 的 gold_text 按相同规则拼接。装载器不触碰 `masked-test`（GT 为空）文件出数。

### 臂位（2×2 + 对照）

```text
              unit 粒度               doc 粒度（拼接大文件）
blocr       blocr@unit              blocr@doc            ← 主要对手
blocr+sys   blocr+system@unit       blocr+system@doc     ← 本系统
参照                              ref-blocr@unit-pieces ← 逐单元重写后拼接
noop        control-noop            control-noop
```

- `ref-blocr@unit-pieces` 隔离"文档变长对重写质量的影响"（长上下文退化）与"臂的差异"；无此臂，doc 轨上 blocr 的 cMER 变化无法归因。
- 外部锚定：unit 轨可与官方已发布成绩比（含 BLOCR 自己的提交）；doc 轨无外部锚，只作内部比较。

## 提示词

共用指令体 = BLOCR 仓库 `ocrepair/postcorrect.py` 的 `SYSTEM_PROMPT` **逐字副本**（MIT），其条款：专家角色、四类修复目标（过度切分 / 切分不足 / 误识字符 / 缺字符，含示例）、人名地名不改、不翻译、保留重音、歧义则原样复制。

两臂各自只替换输出格式条款：

| 臂 | 输出条款 |
|---|---|
| `blocr` | 原样的 JSON 条款（`document_id` + `ocr_postcorrection_output`），逐样本单元素数组；末尾的 `CORRECTIONS_CSV` 日志**保留**——它是 BLOCR 原样的 token 成本 |
| `blocr+system` | fn patch 条款：以 `set_content` / `replace` 等七个操作编辑视图中的块；patch 本身就是结构化改动清单，替代 CSV 日志 |

温度等采样参数两臂一致（0.2，同 BLOCR）；逐样本单条调用，不沿用其批处理（批处理会混淆 token 归因）。

## 指标

### token 效率

| 指标 | 定义 |
|---|---|
| `tokens_in` / `tokens_out` / `tokens_total` | 每样本合计，含重试轮；取自 API `usage` 字段，不做本地估算 |
| `view_overhead` | blocr+system 的标注开销 = len(view payload) − len(原文) |
| `output_ratio` | blocr+system.tokens_out / blocr.tokens_out（同样本配对） |

### 修复性能

直接调用官方 scorer（`related_source/HIPE-OCRepair-scorer-0.9.9`，editable 本地依赖），不重新实现：

- `cmer_micro`（主，越小越好）与 `pref_score_cmer_macro`（副，越大越好），沿用其归一化与 bootstrap 95% CI。
- `track-doc` 以整文件为一个单元算 cMER-micro，报告中注明此为自设口径。

## 公平性控制

- 同一模型、同一采样参数，两臂逐样本配对执行。
- **信息对等**：两臂获得相同的原文与元数据；指令体逐字相同，仅输出格式条款不同。
- 重试预算一致：blocr+system 的 `SurfaceError`/解析失败、blocr 的 JSON 校验失败，均 ≤ 2 次重试，错误信息反馈进下一轮 prompt；重试的 token 计入总量。
- 每样本记录原始 prompt 与响应全文，落盘可审计。

## 架构

`llm` 是与核心模块同级的独立模块；`experiment_app` 是测评的装配层，只经公开接口使用 `llm` 与本系统（`sourceio`/`partition`/`ir`/`reconstruction`/`view`/`surface`），不 import 内部。

```text
src/llm/               # 独立模块：LLM 访问
  client.py            # LLMClient 协议、Completion/Usage 类型
  deepseek.py          # DeepSeek 实现（OpenAI 兼容端点，httpx）
  errors.py            # LLMError（含重试/超时语义）

src/experiment_app/    # 测评装配层
  datasets.py          # jsonl -> Sample；track-doc 拼接
  arms.py              # blocr / blocr+system / ref / noop 四个 runner
  prompts/             # blocr_rewrite.md / blocr_patch.md（共用指令体，输出条款不同）
  score.py             # 官方 scorer 适配器
  run.py               # 执行矩阵 + 原始记录落盘（jsonl）
  report.py            # 汇总表：token × 性能 × 轨 × 语言
  __main__.py          # python -m experiment_app ...
```

### 接口

```python
# src/llm
class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> Completion: ...
# Completion = { text: str, usage: Usage }；Usage = { input_tokens: int, output_tokens: int }

# src/experiment_app
Arm = Callable[[Sample, LLMClient], ArmResult]
# ArmResult = { corrected_text, tokens_in, tokens_out, rounds, raw_log_path }
```

### blocr+system 内部流程

```text
ingest(ocr_text) -> partition_lines -> present(默认组件) -> prompt(view payload) -> LLM -> fn patch
  -> run_patch 成功 -> reconstruct 得修复文本
  -> 失败 -> SurfaceError 反馈进 prompt 重试（≤2 次），超限则标记 failed 并回退原文
```

回退原文的样本在报告中单列，cMER 按实际产出文本计算。

## 验证表（前向假设）

| 假设 | 确认阈值 | 挑战阈值 | 越线动作 |
|---|---|---|---|
| 大文件轨上 blocr+system 的输出 token 显著节省 | `output_ratio` ≤ 0.6 | ≥ 0.9 | 检查块粒度与标注开销；调整 partition |
| blocr+system 修复性能不劣于 blocr | ΔcMER ≤ +0.002 | ΔcMER > +0.01 | 检查 patch 失败/回退率、重试轮分布 |
| 单元轨上 blocr+system 总开销可控 | `tokens_total` ≤ blocr × 1.2 | > ×1.5 | 单元轨从主打场景中移除，仅保留大文件轨结论 |

## 验收

- 冒烟：3 条 dev 样本 × 全臂跑通，report 产出且 token 计数全部来自 `usage` 字段
- 复现：同一批样本同配置运行两次，cMER 完全一致
- 自洽：report 中每样本 `tokens_total == tokens_in + tokens_out`；control-noop 的 cMER 与官方 no-correction 基线同量级（同子集误差在 CI 内）

## 边界

- 不修改 `related_source/` 任何文件；scorer 以 editable 本地依赖接入。
- API key 从环境变量读取，缺省回退到 `deep_seek.txt`（临时凭证，已 gitignore，不进代码与提交）。
- 不追求官方排名；masked-test 不用于出数。

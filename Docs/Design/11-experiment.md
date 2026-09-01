# 实验装配：执行矩阵、对话录与报告

> 前置：[08-llm.md](08-llm.md) / [09-tools.md](09-tools.md) / [10-datasets.md](10-datasets.md)。

## 范围

把三者装成一次实验并产出可审计的结果：

```text
dataset.py × 工具配置 × 模型配置 -> 执行矩阵 -> 对话录落盘 -> 评分 -> 报告
```

`experiment` 是装配层，只经公开接口使用 `llm`、工具集、`dataset.py` 与本系统（sourceio / partition / ir / view / surface），不 import 任何内部。

## 运行配置

```text
python -m experiment --dataset <dir> --toolsets a,b --models m \
    --split dev [--granularity doc] [--ids ...] [--languages de,en] [--limit N] \
    [--instruction <模板名|路径>] --out runs/<name>
```

- `--dataset` 指向含 `dataset.py` 的目录；`--toolsets` / `--models` 把名字解析为 `configs/toolsets/<name>.toml` / `configs/models/<name>.toml`；`--arm-config` 式自定义标签同旧规，可重复挂载任意 TOML。
- `--split` / `--granularity` / `--ids` / `--languages` / `--limit` 原样透传给 `dataset.py` 的 `tasks()`——处理对象的选择权在数据集入口。
- `--instruction` 覆盖 `default_instruction()`；缺省用数据集的。

## 公平性

- 同一实验内：模型配置、终止预算对各工具配置一致；不一致即破坏公平性控制，报告必须注明。
- **信息对等**：各工具配置获得同一 `task.input` 与 `task.meta`；instruction 相同，仅 `prompt_clause` 随工具集不同；提示词拼接顺序固定（见 [09](09-tools.md#loop)）。
- 同一任务、同一模型下各工具配置逐样本配对执行；配对比较才有 `output_ratio` / Δ指标。
- 外部 harness 结果与 in-house 结果同表但分区，口径差异（隐藏提示词开销、usage 来源）在报告中注明（见 [09](09-tools.md#外部-harness-驱动)）。

## 对话录

每轮原始记录落盘于 `runs/<name>/raw/<task_id>/<toolset>.json`：

```json
{ "turns": [
    { "index": 0,
      "messages_ref": "sha256:…",          // 请求消息清单的哈希，全文在 messages/ 目录去重存放
      "completion": { "text": "…", "usage": { … }, "raw": { … } },
      "tool_calls": [ { "name": "…", "args": "…", "feedback": "…" } ] }
  ],
  "status": "done", "output": "…" }
```

- 请求 messages 全文按内容哈希去重存放（多轮前缀大量重复）；对话录可完整重建每一轮的请求与响应，**可审计**。
- **逐轮增量落盘**：每轮完成即追加写盘，不是任务完成后一次性写——长任务被中断时已跑的轮次不白费（踩坑记录 #7）。
- **对话录是不可再生资产**：响应只能由 API 重新付费获得，后处理永远可以重算（踩坑记录 #2）；任何清理操作不得删 `raw/`。
- 续跑（resume）的键 = `(task_id, 工具配置哈希)`——同名配置换了内容必须视为新运行，否则探索期必然吃到陈数据（踩坑记录 #7）。
- 解析后的全部配置（models / toolsets / dataset 入口与 tasks 参数 / instruction 来源）写入 `report.json`，结果可复现。

## replay

当改动只涉及**确定性后处理**（方言解析、工具执行、extract、评分）而不涉及 prompt / 模型 / 工具集时，无需重新调用 LLM：

```text
python -m experiment --out runs/<name> --replay
```

规则：

- 对每个 `(task, toolset)`：从 dataset 入口重建 task，按对话录顺序对每轮已存 completion 重跑后处理；token 计数沿用记录值，不重打 API。
- **prompt、模型或工具集变了 ⇒ 响应本身会变，replay 无效，必须重跑**。replay 重用的是同一盘磁带，不是同一行为。
- 新代码下某轮后处理失败而磁带没有下一轮（真实运行本会多走一轮）⇒ 按 `failed` 回退 `task.input`——此时 replay 是真实重跑的下界，报告注明。
- 配置从旧 `report.json` 读回（当时运行的配置），不用当前 `configs/` 下的同名文件。
- replay 结果写入 `report.json` 的 `replay` 段（`changed` / `lower_bound`）；原始对话录不动。

## 运行时可观测

doc 级任务单篇数分钟，盲跑到结束才知道失败不可接受。实验运行必须让操作者**中途就能判断是否正常、必要时中途打断**。

### 报告器接口（可插拔）

`experiment` 只面向 `ProgressReporter` 协议编程，实现可整体替换（CLI `--reporter rich|null|module:Class`）：

```python
class ProgressReporter(Protocol):
    def begin(self, total: int) -> None: ...        # 矩阵开始，告知 cell 总数
    def start_cell(self, label: str) -> None: ...   # label = "task_id × toolset"
    def turn(self, usage: Usage | None) -> None: ...  # 一轮完成；None = 端点未返回
    def end_cell(self, label: str, status: str,     # done / failed[:kind] / resumed
                 usage: Usage | None, elapsed_s: float) -> None: ...
    def close(self) -> None: ...                    # 运行结束（含 Ctrl+C），释放终端资源
```

- 全部为观察回调，不得影响实验语义；监控输出不进对话录、不进报告。
- 内建 `RichProgress`（rich.Live）：TTY 原地刷新状态行（进度 `done/total`、当前 cell、轮次、墙钟、out token、**TPS**）+ 最近事件行；非 TTY（重定向 / CI）退化为追加事件行，不喷 ANSI；`NullProgress` 为全空缺省。
- token 计数只认端点 usage；报告中的 usage/TPS 以落盘的端点值为准。
- **流式增量显示（模型输出尾部滚动）搁置**：协议不含 `delta`；实现者自行声明 `delta(text)` 后由 run 层探测接入（`getattr`），未声明则走非流式请求。08 的 `on_delta` 管线保留。

### 并发

- `--workers N` 并发执行 cell（默认 1）。并发是实现细节：矩阵、落盘内容、报告与 `workers=1` 逐格执行完全一致。
- 单端点可用并发上限不凭猜：用 `scripts/probe_concurrency.py` 对目标端点做阶梯实测（小请求逐级加压，看失败率与延迟拐点），据实测值选择 `--workers`。

## 报告

`report.json` + 汇总表，维度：指标 × 工具配置 × 切片（语言 / 粒度，取自 `task.meta`）。

| 段 | 内容 |
|---|---|
| 逐样本 | 每 `(task, toolset)`：`ScoreRecord`、各轮与合计 `usage`、`status`、turns 数 |
| token 构成 | `reasoning_tokens` 占比单列——可见输出的压缩优势在思考噪声下兑现不到账单，token 效率的杠杆先看构成（踩坑记录 #5） |
| 配对比较 | 同 task 两工具配置的 `output_ratio`、Δ指标 + bootstrap 95% CI（经 `evalkit.stats`） |
| 配置 | 解析后的 models / toolsets / dataset 入口与参数全量落盘 |
| 口径 | `dataset.info().notes` 原文引用；外部 harness 的 `usage_source` 与口径警示 |

- 指标语义归数据集，报告只按名聚合；`tokens_total == Σ 各轮 usage` 必须自洽。
- 回退原文（`failed`）的样本单列，指标按实际产出文本计算。

## 验收

```text
冒烟：datasets/tiny × noop/rewrite/patch × 录制回放的 stub client 跑通，
     report 自洽（tokens_total == 各轮合计；usage_missing 有标记）
复现：同一批 task 同配置运行两次，ScoreRecord 完全一致
锚点：HIPE 上 noop 的指标与官方 no-correction 基线同量级（同子集误差在 CI 内）
```

## 边界

- 不追求官方排名；masked split 不出数。
- 不修改 `related_source/` 任何文件；外部评分器以本地依赖接入对应 `dataset.py`。
- 并发 worker 与终端渲染是实现细节，不改变矩阵语义与落盘内容（见[运行时可观测](#运行时可观测)）。
- 实验结论的解释限定（任务场景与测评口径的错配等）归数据集 `info().notes` 与报告口径段，不在本框架内硬编码。

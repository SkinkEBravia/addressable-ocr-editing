# 数据集契约与评测

> 前置：被 [11-experiment.md](11-experiment.md) 装配；评测原语来自公共组件库 `evalkit`。

## 范围

任务的正式承载物是**数据集**。本模块只规定 `dataset.py` 的接口契约——**物理布局完全隔离在契约背后**：OCR 与 gold 怎么分存、jsonl 还是目录树、远程还是本地，都是各数据集内部的事。

```text
一个数据集 = 一个目录 + 一个 dataset.py
换任务 = 换 dataset.py + 换 instruction（工具配置与 IR 系统不动）
```

契约按**文本进、文本出**的任务定义；非文本任务所需的泛化见「边界」。

## 契约

`dataset.py` 必须暴露四个入口：

```python
def loaders(*, split: str) -> dict[str, Loader]: ...  # Loader = () -> Iterable[Task]

def scorer() -> Scorer: ...
def default_instruction() -> str: ...     # 任务指令原文（如 BLOCR SYSTEM_PROMPT 逐字副本）
def info() -> DatasetInfo: ...
```

### loader 风格的选择接口（torch 式）

数据集提供**一组具名 loader**，每个 loader 是一条独立的 Task 流；**组合权在调用方**（实验装配、unit 测试）——取子集 = 按键选 loader，全量 = `itertools.chain` 串联，`ids` / `limit` 截断在数据集之外完成：

```text
loaders(split="dev") -> {
    "icdar2017/en/chunk":  () -> Iterable[Task],
    "icdar2017/en/doc":    () -> Iterable[Task],
    "dta19-l0/de/chunk":   () -> Iterable[Task],
    ...
}
```

- **key 即选择器**，命名方案归数据集所有，必须写入 `info().notes`（如 HIPE：`<subset>/<language>/<granularity>`）。
- 同一 key 的 loader 多次调用产出**逐字段相同**的 Task 序列（可重放、可配对）。
- 不同 key 的 Task 流 `task_id` 全局不撞（串联安全）。
- loader 是零参 callable 而非直接暴露 iterable：装载时机归调用方，map-style 惰性由数据集自决。
- 数据集内部的最小读取单位与分组规则（如 HIPE 的 chunk 原子 + doc 分组视图）是实现细节，不进入契约。

### `Task`

数据接口。"LLM 要修改的东西" + 评判依据。

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | `str` | 数据集内唯一，落盘与报告的主键 |
| `input` | `str` | 待处理文本（OCR 修复任务即 OCR 原文） |
| `reference` | `str \| None` | gold；`None` = masked，不参与出数 |
| `meta` | `Attrs` | 语言、来源子集等，报告切片维度 |

### `Scorer`

```python
class Scorer(Protocol):
    def score(self, prediction: str, task: Task) -> ScoreRecord: ...

ScoreRecord = dict[str, float]            # 指标名 -> 值
```

- 指标名与算法归数据集所有；报告层只按名聚合与配对比较，**不解读语义**。
- 对 `reference is None` 的 task 调用 `score` ⇒ `ScoreError`；调用方保证 masked 不出数。
- 数据集专有评测逻辑写在该数据集的 `dataset.py` 里（如 HIPE 适配官方 scorer），可 import `evalkit` 的公共原语。

### `DatasetInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | 数据集名 |
| `version` | `str` | 版本 |
| `splits` | `tuple[str, ...]` | 可用 split |
| `notes` | `str` | 口径与合理性限定 + loader key 命名方案，**必须非空**——结论解释所需的限定条件成文于此，随报告引用 |

## 公共组件库 `evalkit`

任务无关的评测原语；`dataset.py` 的实现与报告层都可 import：

| 组件 | 内容 |
|---|---|
| `evalkit.stats` | bootstrap CI、配对差值检验 |
| `evalkit.usage` | 多轮 `Usage` 合计、配对 `output_ratio` |
| `evalkit.textnorm` | 通用文本归一化 |

边界：`evalkit` 不认识任何具体数据集；知道 HIPE / 官方 scorer 的代码只能出现在 `datasets/hipe_2026/dataset.py` 里。

## 测试入口

- 测试代码集中于一个 `tests/` 包内再细分（unit / docs / 契约测试）；`src/` 核心（sourceio / partition / ir / view / surface）对 datasets、evalkit、experiment **零依赖** ⇒ IR system 可原样发布给他人。
- 夹具数据集 `datasets/tiny/`：同样实现完整契约的微型数据集。测试切换目标数据集 = 改 `dataset.py` 入口，**不复制文件**。
- 契约测试只有一份，对 `tiny` 与任何真实数据集同样运行。

## 验收

```text
datasets/tiny 与 datasets/hipe_2026 均通过同一份契约测试（loaders / scorer / default_instruction / info）
masked（reference = None）样本在任何路径下都不会进入 score
info().notes 非空且含 loader key 命名方案；同一 key 重复调用产出一致；跨 key task_id 不撞
```

## 边界

- 不规定存储布局、文件格式、指标集合、loader 数量与命名——全在契约背后。
- 契约覆盖文本进、文本出的任务；非文本处理对象（图像、多文件）需要泛化 `Task.input` / `Scorer` 类型，属后续版本，届时契约升级而非打破。
- LLM 配置与工具配置归 [08](08-llm.md) / [09](09-tools.md)；执行与报告归 [11](11-experiment.md)。

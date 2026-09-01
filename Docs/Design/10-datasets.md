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
def tasks(*, split: str,
          granularity: str | None = None,
          ids: list[str] | None = None,
          languages: list[str] | None = None,
          limit: int | None = None) -> Iterable[Task]: ...

def scorer() -> Scorer: ...
def default_instruction() -> str: ...     # 任务指令原文（如 BLOCR SYSTEM_PROMPT 逐字副本）
def info() -> DatasetInfo: ...
```

### `Task`

数据接口。"LLM 要修改的东西" + 评判依据。

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | `str` | 数据集内唯一，落盘与报告的主键 |
| `input` | `str` | 待处理文本（OCR 修复任务即 OCR 原文） |
| `reference` | `str \| None` | gold；`None` = masked，不参与出数 |
| `meta` | `Attrs` | 语言、来源子集等，报告切片维度 |

### 处理对象的选择

"1 个文档还是多个"收编进 `tasks()` 参数，**调用方（实验装配、unit 测试、doc 测试）只改入口参数，不触碰文件**：

- `granularity`：任务粒度。取值集与口径由各数据集自定，必须写入 `info().notes`（如 HIPE：`unit` 与官方可比，`doc` 整页为自设口径）。
- `ids` / `languages` / `limit`：子集选择；同一实验内对各工具配置一致（公平性，见 11）。

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
| `granularities` | `tuple[str, ...]` | 可用粒度 |
| `notes` | `str` | 口径与合理性限定，**必须非空**——结论解释所需的限定条件成文于此，随报告引用 |

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
datasets/tiny 与 datasets/hipe_2026 均通过同一份契约测试（tasks / scorer / default_instruction / info）
masked（reference = None）样本在任何路径下都不会进入 score
info().notes 非空；granularity 取值与 notes 中声明的一致
```

## 边界

- 不规定存储布局、文件格式、指标集合——全在契约背后。
- 契约覆盖文本进、文本出的任务；非文本处理对象（图像、多文件）需要泛化 `Task.input` / `Scorer` 类型，属后续版本，届时契约升级而非打破。
- LLM 配置与工具配置归 [08](08-llm.md) / [09](09-tools.md)；执行与报告归 [11](11-experiment.md)。

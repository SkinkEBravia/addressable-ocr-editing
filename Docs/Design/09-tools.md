# 工具配置与 Loop

> 前置：[LLM 客户端](08-llm.md)；IR 操作面与方言 [07-agent-api.md](07-agent-api.md)。

## 范围

实验中被比较的对象是**工具配置**：一次运行给 LLM 暴露什么操作面。

```text
工具配置 = 工具集 + 方言 + 提示词条款 + 终止预算
```

rewrite（全文重写）= 空工具集，不再是特殊通道。单发 patch = 一轮即 `Done` 的退化形态。
本模块定义 loop 驱动与工具集契约；数据集归 [10](10-datasets.md)，执行矩阵归 [11](11-experiment.md)。

## 定义

### `Tool`

```python
class Tool(Protocol):
    name: str
    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult: ...
```

- `ToolContext`：工具的运行环境，**每任务一份**，由 loop 在任务开始时创建（patch 工具的 ctx 持有会话 store 与当前 View）。
- `ToolResult = { ok: bool, feedback: str }`；`feedback` 原样作为 user 消息进入下一轮——**工具报错即对话反馈**，不存在独立的重试机制（取代旧框架的重试预算）。

### `ToolSet`

工具集对外四件套：

| 成员 | 类型 | 说明 |
|---|---|---|
| `tools` | `tuple[Tool, ...]` | 可为空（rewrite） |
| `parse` | `(text) -> tuple[ToolCall, ...] \| Done \| ParseError` | 方言解析器：assistant 文本 → 工具调用 |
| `prompt_clause` | `str` | 工具使用条款，逐字进提示词；**归属权在工具集** |
| `extract` | `(ctx) -> str` | 产出提取：patch = 从 store 重建当前快照；rewrite = 末轮 assistant 文本 |

- 方言 = 文本格式 + 解析器，可替换点同 [07](07-agent-api.md#patch-方言)：换方言只换解析器。
- `Done` = 模型自判完成，标记形式由各工具集方言定义（如独立一行 `done()`）。
- 同一轮多个 `ToolCall` 按文本顺序执行，后续调用看到前面调用的结果（沿用 07 的链式叠加语义）。

### 终止预算 `Budget`

| 字段 | 类型 | 说明 |
|---|---|---|
| `max_turns` | `int` | 轮数上限 |
| `token_budget` | `int \| None` | 累计 `tokens_total` 上限 |

任一耗尽 ⇒ `status = budget_exceeded`，仍执行 `extract` 产出，报告中单列。预算是公平性控制的一部分：跨工具配置比较时必须一致。

### 工具配置（TOML）

每配置一个 TOML 文件，默认放 `configs/toolsets/`，文件名即报告标签。

```toml
# configs/toolsets/patch.toml
toolset      = "patch"    # 包内标准工具集名；含 "/" 或 ".py" 则按相对本文件的路径解析外挂工具集
max_turns    = 8
token_budget = 60000
```

未知键直接报错；解析后的完整配置随报告落盘（见 11）。

## Loop

```python
def run_loop(client: LLMClient, task_input: str, toolset: ToolSet,
             budget: Budget, instruction: str) -> LoopResult

LoopResult = { output: str,                              # extract 的产物
               status: "done" | "budget_exceeded" | "failed",
               turns: list[Turn],
               total_usage: Usage | None }
```

行为规则：

1. **提示词组装**：首条 user 消息 = `instruction` + `prompt_clause` + `task_input`，顺序固定、逐字拼接、进对话录。instruction 属任务（默认来自数据集，见 [10](10-datasets.md)），prompt_clause 属工具集——两段各有主人，拼接口径全实验一致。
2. 每轮：`complete` → `parse` → 按序 `invoke` → feedback 进下一轮；`parse` 得 `Done` ⇒ `extract` 后结束。
3. `ParseError` 与工具失败走同一通道：作为 feedback 进下一轮。
4. 轮内不截断历史；历史管理（压缩/截断）不在 v1。

## 标准工具配置

第一版交付的标准集；每个都是同契约下的普通配置：

| 名 | tools | 说明 |
|---|---|---|
| `noop` | — | 不调 LLM，`output = input`；no-correction 锚点对照 |
| `rewrite` | 空 | 单轮全文重写，输出条款进 `prompt_clause` |
| `patch` | `view` / `run_patch`（经 [07](07-agent-api.md) 公开接口，fn 方言） | 本系统 |
| `rewrite_pieces` | 空 | 逐单元重写后拼接（doc 粒度的归因参照） |
| `find_replace` | `read` / `find_replace(old, new)` | 常见 harness 最小编辑工具的复刻 |

**agent 对块的定位一律用 `AgentBlockId`**（定义见 [06](06-view.md#agentidstrategy)）：工具参数、prompt_clause 示例、feedback 中出现的块标识都是 Agent 侧 id，降解时经 `ReferenceMap` 换回 `BlockKey`；工具集与 loop 不得把 `BlockKey` 泄漏进对话。

codex 式工具集（shell + 文件编辑）作为后续标准配置加入，走同一契约——与 codex 的比较是**同口径的工具集复刻对比**，外加下文的外部 harness 对比。

## 工具暴露

本系统的操作面要能被外部 harness 使用。操作面的两种进程化封装——CLI 与 MCP 服务（Streamable HTTP）——归 [07](07-agent-api.md) 定义（MCP 也是给 Agent 的一种 API，同属操作面入口）；两者共享方言、错误格式与会话目录。本模块只消费这一事实：`HarnessConfig` 的"工具暴露方式"字段选择挂 CLI 还是 MCP。

## 外部 harness 驱动

横向比较 harness 本身（codex 等，包括"别的 harness 用不用本系统"）时，driver 换成外部进程：

```python
def run_external(harness: HarnessConfig, task_input: str,
                 instruction: str, workdir: Path) -> LoopResult
```

- `HarnessConfig`：命令模板、工具暴露方式（本系统以 CLI / MCP 挂给外部 harness）、usage 提取方式。
- 产出与 `run_loop` 同一 `LoopResult` 契约 ⇒ 评分、落盘、replay 无差别复用。
- usage 取 harness 自报；取不到记 `None`。
- **口径警示**：外部 harness 含其自有隐藏提示词与内部流程开销，与 in-house loop 不 token 对账；报告必须注明此为 harness 级口径，不与工具配置级口径混排。

## 验收

```text
noop：全任务 status = done 且 output == input
注入 ParseError ⇒ 下一轮消息含错误反馈；代码中无独立重试路径
budget 耗尽 ⇒ status = budget_exceeded 且 output 仍产出
同一 (client stub, task, toolset, budget) 运行两次 ⇒ LoopResult 逐字段相同
```

## 边界

- 不定义任务、gold 与评分（[10](10-datasets.md)）；不定义执行矩阵、对话录落盘与报告（[11](11-experiment.md)）。
- patch 工具只经本系统公开接口（[05](05-ir-io.md) / [06](06-view.md) / [07](07-agent-api.md)）使用 IR，不 import 内部。
- 跨任务复用 `ToolContext`、并发执行不在 v1。

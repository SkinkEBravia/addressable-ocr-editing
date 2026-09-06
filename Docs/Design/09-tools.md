# Session、工具契约与 Loop

> 前置：[LLM 客户端](08-llm.md)；IR 操作面与方言 [07-agent-api.md](07-agent-api.md)。

## 范围

实验中被比较的对象是**工具配置**：一次运行给 LLM 暴露什么操作面。

```text
工具配置 = 工具集 + 方言 + 提示词条款 + 终止预算
```

本模块定义三样东西：**Session**（一次对话的全部状态与磁带格式）、**工具契约**（四件套）、**loop**（驱动 Session 的引擎）。数据集归 [10](10-datasets.md)，执行矩阵归 [11](11-experiment.md)。

## 数据流

```text
组装上下文   (Task, instruction, 工具配置) -> 初始 messages + Budget      // 本模块，纯函数
agent loop   初始 messages × LLMClient -> Session                          // 逐轮增量落盘
             轮内: complete -> parse -> 工具 fold -> feedback 回灌对话      // 反馈边
工具应用     Session.fold 末态 -> extract -> SourceText                    // replay 同一函数
```

评测消费 `SourceText`（指标）与 `Session`（usage / failure），归 [11](11-experiment.md)。

## `Session`

一次 (task, toolset) 对话的**运行时状态与落盘磁带是同一个结构**（序列化时剥掉运行期专属字段即磁带）。每轮结束原子重写全量 JSON——增量落盘，中断时已跑轮次不白费。

```python
@dataclass
class Session:
    version: int              # 磁带格式版本（演进时 +1，读取方按版本解释）
    task_id: str
    toolset: str              # 工具配置名（报告标签）
    config_hash: str          # resume 键的一部分，由 experiment 计算（见 11）
    budget: Budget
    turns: list[Turn]         # append-only
    status: str               # running | done | budget_exceeded | failed:<kind>
    failure: Failure | None   # 失败现场；挂在 Session 而非 Turn——turn-0 失败时 turns 为空
    tool_state: dict          # 工具集私有的运行期状态；loop/experiment 不得读写；不落盘

@dataclass
class Turn:
    index: int
    request: tuple[Message, ...]                    # 落盘：全文按内容哈希去重存 messages/
    completion: Completion
    calls: tuple[ToolCall, ...]
    results: tuple[ToolResult, ...]                 # 与 calls 对齐
    parse_error: str | None

@dataclass
class Failure:                                       # 三通道之「失败通道」的统一载荷
    stage: str          # llm | tool | extract
    kind: str           # llm 阶段的 kind 定义见 08；tool/extract 阶段自由命名
    message: str
    http_status: int | None
    attempts: int
    elapsed_s: float | None
    detail: dict
```

规则：

- **预设成员 = 跨工具集契约**；新增跨组件信息一律升格为预设成员，不走 `tool_state`。
- `tool_state` 的 key 归工具集所有并自行文档化；工具自己的持久状态（patch 的 IR store）由工具集按自己的方式存放（workdir），磁带只存 calls/results——replay 重 fold 即重建。
- usage 不设成员：**派生**自各轮 `completion.usage` 之和；任一轮缺失则整体 `usage_missing`。
- 磁带是不可再生资产：响应只能由 API 重新付费获得；任何清理操作不得删磁带。

## 工具契约

工具集对外四件套 + 输入呈现；每个成员只被一个阶段消费：

| 成员 | 类型 | 消费阶段 | 说明 |
|---|---|---|---|
| `prompt_clause` | `str` | 组装 | 工具使用条款，逐字进 system 消息；归属权在工具集 |
| `present_input` | `(input, tool_state) -> str` | 组装 | 首条 user 消息中输入的呈现（patch = 标注视图；其余 = 原文） |
| `parse` | `(text) -> tuple[ToolCall, ...] \| Done` | loop | 方言解析器；失败抛 `ToolParseError` |
| `invoke` | `(call, tool_state) -> ToolResult` | loop / replay | 工具 fold 的一步；同一 fold 内后续调用看到前面的结果 |
| `extract` | `(tool_state, session) -> SourceText` | 工具应用 | fold 末态 -> 产出文件 |

- 工具集另声明 `name: str` 与 `uses_llm: bool`（noop 为 False：零轮迭代，`extract` 恒等回原文）。
- 方言 = 文本格式 + 解析器，可替换点同 [07](07-agent-api.md#patch-方言)：换方言只换 `parse`。
- `Done` = 模型自判完成。标记形式：`done()`（或 `done`）——可单独一行，**也可作为消息最后一行**（先按序执行前面的调用，再由工具返回 `finish=True` 收束）；出现在中间则判方言错误。
- `ToolResult = { ok: bool, feedback: str, finish: bool = False }`；`feedback` 原样作为 user 消息进入下一轮——**工具报错即对话反馈**，无独立重试机制。`finish=True` = 工具侧宣告对话完成（顺序任务的自然终止，如逐单元修复的末单元）：loop 在本轮落盘后以 `done` 收束，不再追加 feedback。
- 工具集构造运行环境：`make_tool_state(task_input, task_meta, workdir) -> dict`（loop 在 Session 开始时调用一次）。
- **agent 对块的定位一律用 `AgentBlockId`**（见 [06](06-view.md#agentidstrategy)）：工具参数、prompt_clause 示例、feedback 中的块标识都是 Agent 侧 id；工具集与 loop 不得把 `BlockKey` 泄漏进对话。

### 工具资产与 workdir 生命周期

每个 cell 的工具集持有一个独立 workdir（由 experiment 创建，`runs/<name>/work/<task_id>/<toolset>/`），它是工具的**操作 scope**。生命周期三段：

```text
init      装配期：make_tool_state(task_input, meta, workdir) 在 loop 开始前
          布置资产——patch 建 IR store，swe_bash 写 text.txt + bin/edit
operate   loop 期：invoke 只经 tool_state（及 workdir 内资产）读写
read-out  收尾：extract 从资产读出产出，规范化成 SourceText
```

规则：

- **scope 归工具**：工具不得读写 workdir 之外（shell 后端是尽力约束——无沙箱时模型命令理论上可越界，口径见 09 标准配置 swe_bash 条与 11；接受此风险只为可信实验输入）。
- **产出约定**：工具集必须声明自己的资产布局与产出文件（swe_bash：产出 = `text.txt`，条款同步告诉模型就地编辑），`prompt_clause` 与 `extract` 以之为同一约定。模型写到约定之外 = 回退原文 + `Failure(stage="extract")`，语义自洽。
- **extract 即 output processor**：评测的唯一输入是 extract 规范化的 `SourceText`；不设独立的 output_processor 层——「从哪读产出、怎么解释」是工具集私有知识，独立层只会复制这个 seam 或掩盖错误。评测对象超出 SourceText 时是 extract 返回类型的契约泛化（见 [10](10-datasets.md#边界)），不是新增一层。
- **workdir 是可重放草稿**：`work/` 可由磁带重 fold 重建，清理不影响审计；不可再生资产只有 `sessions/`。replay 使用独立的 `replay-work/` workdir，不污染原运行现场。

### 终止预算 `Budget`

| 字段 | 类型 | 说明 |
|---|---|---|
| `max_turns` | `int` | 轮数上限 |
| `token_budget` | `int \| None` | 累计 tokens（input+output）上限；任一轮 usage 缺失则该维度不检查 |

任一耗尽 ⇒ `status = budget_exceeded`，仍执行 `extract` 产出。预算是公平性控制的一部分：跨工具配置必须一致。

### 工具配置（TOML）

每配置一个 TOML 文件，默认放 `configs/toolsets/`，文件名即报告标签。

```toml
# configs/toolsets/patch.toml
toolset      = "patch"    # 包内标准工具集名；含 "/" 或 ".py" 则按相对本文件的路径解析外挂工具集
max_turns    = 8
token_budget = 60000
```

未知键直接报错；解析后的完整配置随报告落盘（见 11）。

## 组装上下文

```python
def build_initial_messages(instruction: str, prompt_clause: str,
                           presented_input: str, task_meta: dict) -> list[Message]
```

- `system` = `instruction` + `prompt_clause`（顺序固定、逐字拼接）；instruction 属任务（默认来自数据集，见 [10](10-datasets.md)），prompt_clause 属工具集——两段各有主人，拼接口径全实验一致。
- 首条 `user` = 输入呈现的通用包装：`--- INPUT (language: …) ---\n…\n--- END OF INPUT ---`。
- 组装函数只有一个，loop 与任何多上下文变体共用。

## Loop

```python
def run_session(client: LLMClient, toolset: ToolSet, session: Session,
                initial_messages: list[Message],
                on_turn: Callable[[Session], None] | None = None,
                on_delta: Callable[[str], None] | None = None) -> Session
```

行为规则：

1. 每轮：`complete` -> `parse` -> 按序 `invoke` -> feedback 进下一轮；`parse` 得 `Done` ⇒ 结束。
2. `ToolParseError` 与 `ToolResult(ok=False)` 走**对话通道**：作为 feedback 进下一轮，不进异常。
3. `LLMError` 走**失败通道**：`session.failure = exc.failure`，`status = failed:<kind>`，回退产出 = 原文。
4. 工具 `invoke` 的**意外异常**（非领域错误的 `ToolResult`）：catch 后记 `Failure(stage="tool")` 并 fail——这是我们的 bug，不喂给模型浪费轮次；`detail` 带 traceback 摘要。
5. 每轮完成即 `on_turn(session)` 回调（experiment 借此增量落盘）；`on_delta` 原样透传 client 的观察通道。
6. 轮内不截断历史；历史管理（压缩/截断）不在本版。
7. `uses_llm = False`（noop）：零轮迭代，`status = done`，`extract` 回原文。

确定性验收：同一 (StubClient 剧本, task, toolset, budget) 运行两次 ⇒ Session 逐字段相同。

## 工具应用与产出

```python
extract: (tool_state, session) -> SourceText   # SourceText 见 01（text + encoding + bom）
```

- 产出类型是 `SourceText`：patch = 从 store reconstruct（保真链路的产物）；rewrite 系 = 模型文本的归一结果（`encoding="utf-8", bom=b""`）。评测取 `.text`（见 11）。
- 为什么给 `session`：rewrite 的 fold 状态就是对话本身（末轮 assistant 文本），不给 session 就得靠 loop 往 tool_state 里塞隐式通道——明确给参比暗道干净。patch 忽略 session。
- `extract` 抛异常 ⇒ `Failure(stage="extract")`，回退产出 = 原文（可评分，不空转）。
- **fold 是确定性函数**：(初始 tool_state, 逐轮 calls 与 completion) -> 末态。replay 从磁带重 fold，不调 LLM（见 [11](11-experiment.md#replay)）。
- `Session` 另设预设成员 `output: str | None`：extract 产出的 `SourceText.text`（失败回退原文也写入）；cell 结束时必有值，评测与报告直接消费。

## 标准工具配置

| 名 | tools | 说明 |
|---|---|---|
| `noop` | — | `uses_llm = False`，output = input；no-correction 锚点对照 |
| `rewrite` | 空 | 单轮全文重写，输出条款进 `prompt_clause` |
| `patch` | `view` / `run_patch`（经 [07](07-agent-api.md) 公开接口，fn 方言） | 本系统 |
| `find_replace` | `read` / `find_replace(old, new)` | 常见 harness 最小编辑工具的复刻（字符串锚，Aider / Claude Code Edit 流派） |
| `swe_edit` | `view` / `edit(start, end, "text")` | 经典 SWE-agent v0.7 行号锚编辑的复刻（参照 related_agents/swe-agent-classic，MIT） |
| `swe_bash`〔harness，暂不参与实验〕 | `bash("cmd")` | SWE-agent 环境忠实复刻：模型只有一个 bash 入口，edit 是 PATH 上的脚本；ShellBackend 可替换（本机 GitBashBackend，无沙箱可信输入专用；DockerBackend 待有 Docker 的环境） |
| `rewrite_seq` | `submit`（隐式） | 逐单元顺序重写：一文档一场对话，每轮呈现一个单元，每单元一次机会，**无反馈口径**（工具结果/错误不回灌，对齐 rewrite）；末单元 `finish=True` 收束 |
| `patch_seq` | `run_patch`（隐式） | 逐单元顺序 patch：同上口径；每单元独立 IR 会话（块 id 每单元重排）；建议配 `apply_mode = "best_effort"`（单机会下原子批过脆） |
| `swe_edit_seq` | `edit`（局部作用域） | 逐单元顺序行号编辑：行号每单元从 1 重排，只能编辑当前单元 |
| `find_replace_seq` | `find_replace`（局部作用域） | 逐单元顺序字符串替换：替换只在当前单元生效 |
| `patch_global_seq` | `run_patch`（**全局作用域**） | 前缀命名空间块 id（`c0:b1`、`c1:b2`），可跨单元路由，**允许回溯编辑此前呈现过的任何单元** |
| `swe_edit_global_seq` | `edit`（**全局作用域**） | 显式文件寻址（`edit chunk_0 1:2`），行号作用域被文件名隔离 |
| `find_replace_global_seq` | `find_replace`（**全局作用域**） | 替换作用于当前及历史全部已呈现单元 |

### 作用域：单轮 / 局部顺序 / 全局顺序

工具集不是扁平列表，而是 **寻址机制 × 作用域** 的二维：

| 作用域 | 一次对话看到什么 | 能改什么 | 命名 |
|---|---|---|---|
| **单轮** | 全部输入一次给出 | 全部 | 无后缀（`patch` / `swe_edit` / …） |
| **局部顺序** | 每轮一个单元 | **仅当前单元**；id / 行号每单元重排 | `_seq` |
| **全局顺序** | 每轮一个单元，带文件标识抬头 | **当前 + 全部历史单元**；靠前缀命名空间寻址（见 [06](06-view.md) 的 `present_file` / `prefixed_blockkey`） | `_global_seq` |

`rewrite` 系没有全局作用域 —— 它不具备寻址能力，无法指向此前的单元。

### `patch` 暴露的操作集

**无后缀的 `patch` 暴露 `fn` 方言的全部七个 SurfaceOp**（见 [07](07-agent-api.md#surfaceop-标准集)）：

`replace` / `set_content` / `set_attrs` / `append` / `remove` / `move` / `merge`

> [!danger] `hide_ops` 只裁剪提示词，**不拦截操作**
> `hide_ops` 作用于 `patch_clause()` 生成的操作清单 —— 被隐去的操作**不再出现在提示词里**，
> 但 `surface.run_patch` 对它一无所知：模型若仍吐出该操作，**照样解析、照样应用**。
>
> ⇒ `hide_ops` 是**给模型的建议**，不是系统施加的约束。
> ⇒ 因此**工具集名不得据 `hide_ops` 声称受限的操作集** —— 那会让名字撒谎。
> 若要一个真正受限的操作面，必须在 `parse` / `degrade` 层拒绝清单外的操作，并作为**独立的注册表键**存在。

### 命名规则

```text
<寻址机制>[_<操作子集>][_<作用域>]
```

- **寻址机制**：`rewrite` / `patch` / `swe_edit` / `find_replace`
- **操作子集**：省略 = **全集**。仅当系统**真正拒绝**清单外操作时才可加后缀（见上方警告）
- **作用域**：省略 = 单轮；`_seq` = 局部顺序；`_global_seq` = 全局顺序

同一注册表键在不同 `toml` 下的行为差异（`apply_mode` / `partition` / 预算）由**报告标签**（toml 文件名）承载，
但**凡是改变模型可见操作面的差异，必须体现在注册表键上**，不能只靠 toml 文件名区分。

顺序工具集（`*_seq`）的 `parse` 永不抛错（任何响应都视为该单元的提交）；`max_turns` 只是安全上限，实际轮数 = 单元数。patch 系工具配置支持 `apply_mode`（atomic | best_effort，见 [07](07-agent-api.md#应用策略可替换件)）与 `hide_ops`（提示词操作清单裁剪）。

> [!important] seq 变体与其单轮对应臂**共享提示词**（有意的口径绑定）
> `sequential.py` 复用 `agent.patch.patch_clause` 与 `agent.standard.REWRITE_CLAUSE` /
> `extract_rewrite_text`，以保证「同一寻址机制在不同作用域下条款一致」。
> ⇒ **改动单轮臂的 `prompt_clause` 会静默改变对应 seq 臂的实验口径**，破坏跨批次可比性。
> 调整任一方前，先确认另一方是否需要同步冻结。

多对话变体（如逐单元重写后拼接的 rewrite_pieces）由**组装层**产生多个 Session 实现，不走 loop 变体；本版暂不提供，需要时按组装接口加。

## 外部 harness 驱动

横向比较 harness 本身（codex 等）时，driver 换成外部进程，产出**同一个 Session 结构**（turns 里 messages 可为 harness 侧摘要，usage 取 harness 自报、取不到记 None）⇒ 评分、落盘、replay 无差别复用。

- **口径警示**：外部 harness 含其自有隐藏提示词与内部流程开销，与 in-house loop 不 token 对账；报告必须注明此为 harness 级口径，不与工具配置级口径混排。
- 本系统的操作面经 CLI / MCP 挂给外部 harness，封装归 [07](07-agent-api.md)；本模块只消费这一事实。

## 验收

```text
noop：全任务 status = done 且 output == input，turns 为空
注入 ToolParseError ⇒ 下一轮 messages 含错误反馈；代码中无独立重试路径
budget 耗尽 ⇒ status = budget_exceeded 且 extract 仍产出
LLMError ⇒ Session.failure 逐字段完整（kind/message/http_status/attempts/elapsed_s），status = failed:<kind>
工具 invoke 抛意外异常 ⇒ Failure(stage="tool")，details 含 traceback 摘要
空 completion 不产生 Turn（08 已在 client 层拦截）
同一 (stub, task, toolset, budget) 运行两次 ⇒ Session 磁带逐字节相同
```

## 边界

- 不定义任务、gold 与评分（[10](10-datasets.md)）；不定义执行矩阵、磁带目录布局与报告（[11](11-experiment.md)）。
- patch 工具只经本系统公开接口（[05](05-ir-io.md) / [06](06-view.md) / [07](07-agent-api.md)）使用 IR，不 import 内部。
- 跨任务复用 tool_state、loop 内并发不在本版（并发在 cell 之间，见 [11](11-experiment.md)）。

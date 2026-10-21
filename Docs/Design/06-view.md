# 视图（View）

> 前置概念：[View 与 Agent 操作面](../Concepts/04-view.md)；快照：[03-ir-data.md](03-ir-data.md#documentsnapshot)

## 范围

快照的消费方之一：`DocumentSnapshot -> View`。
定义 `View`、`Presenter`、`AgentView`、`ReferenceMap`、`AgentBlockId` 策略与标注形式。
不定义 patch 方言与解析（见 `07-agent-api.md`）。

## 定义

### View

`View` 是从文档快照导出的对象，服务于特定目的，是快照的派生表示。

| 字段 | 类型 | 含义 |
|---|---|---|
| `view_id` | `ViewId`（`str`） | 视图身份 |
| `snapshot_id` | `SnapshotId` | 来源快照的身份 |
| `payload` | `JsonValue` | 展示内容 |
| `render_spec` | `Attrs` | 呈现配置的描述信息 |

### AgentView

`AgentView` 是面向 Agent 的文本视图，继承 View 的字段，并收窄 payload 类型、增加地址映射。

| 字段 | 类型 | 含义 |
|---|---|---|
| `payload` | `str` | 按快照块顺序生成的展示文本 |
| `reference_map` | `ReferenceMap` | Agent 地址与块身份的双向映射 |

Agent 侧的块地址称为 `AgentBlockId`，类型为 `str`。它与 BlockKey 的用途不同，但值可以相同。展示文本是否包含可见 ID 标注由标注形式决定。

AgentView 可以完全不带标注：使用 plain 时，present 的 payload 与当前正文相同，可用于 rewrite 对照。reference_map 仍可存在，不要求 Agent 在这类任务中使用它。

### ReferenceMap

`ReferenceMap` 保存 AgentBlockId 与 BlockKey 的双射。

| 字段 | 类型 | 含义 |
|---|---|---|
| `forward` | `dict[AgentBlockId, BlockKey]` | Agent 地址到块身份的映射 |

反向映射由 forward 派生。随完整 AgentView 生成的映射覆盖来源快照的全部 blocks。

### AgentIdStrategy

```python
AgentIdStrategy = (block: Block, index: int) -> AgentBlockId
```

ID 策略决定块在 Agent 侧的地址。index 从 0 开始，表示块在传入序列中的位置。

策略可以读取整个 Block，包括 attrs。同一序列中产出的 AgentBlockId 必须互不相同；给定相同输入与配置，策略应产出相同地址。

### Annotator

```python
Annotator = (agent_id: AgentBlockId, content: str) -> str
```

标注形式决定一个块如何展示。它可以加入 ID 标注，也可以忽略 ID、原样返回内容。

ID 策略与标注形式独立，由 Presenter 组合使用。比较 ID 策略时应保持标注形式不变，避免同时改变两个实验变量。

## 字段语义

### view_id 与 snapshot_id

view_id 标识完整视图数据，snapshot_id 标识其来源状态。同一快照可以产生不同视图；视图身份不能替代快照身份，也不能用于推断文档是否发生编辑。目标规则是相同的最终视图数据得到相同的 ViewId。

### payload

payload 按输入块序列的顺序生成，标注和抬头属于展示内容，不写回快照。使用无标注的 plain 时仍生成地址映射，只是 payload 不显示地址。

对完整快照使用 plain 得到的块内容拼接等于当前正文；这不包含编码与 BOM 的恢复，也不承担文件字节还原职责。

### render_spec

当前呈现接口记录 kind、strategy 和 annotator 的名称。组件名称优先取其 `__name__`，否则取可调用对象的类型名；带抬头的呈现还记录 filename、prefix 和 label。

render_spec 是呈现信息的描述，不是完整可执行配置，不能仅凭组件名称保证恢复任意策略实例。

### 地址映射

| 接口 | 输入与输出 |
|---|---|
| `key_of(agent_id)` / `reference_map[agent_id]` | AgentBlockId → BlockKey |
| `agent_id_of(key)` | BlockKey → AgentBlockId |
| `items()` | 返回正向映射条目的 tuple |
| `as_dict()` | 返回正向映射字典的副本 |

未知地址或块 key 的查询抛出 KeyError。映射本身不读取文档，也不更新文档状态。

### ViewId 的计算

ViewId 根据最终生成的视图数据计算，排除 view_id 自身，避免循环依赖。对 AgentView，哈希对象为：

```text
data = {
    "snapshot_id": view.snapshot_id,
    "payload": view.payload,
    "render_spec": view.render_spec,
    "reference_map": view.reference_map.as_dict()
}
ViewId = "v-" + SHA256(UTF8(canonical_json(data))) 的前 16 位十六进制字符
```

普通 View 使用 snapshot_id、payload 和 render_spec；AgentView 另包含正向地址映射。反向索引是派生缓存，不参与哈希。canonical_json 沿用 03 的规范化 JSON 规则，不直接对 dataclass 对象或函数对象计算哈希。

哈希覆盖实际输出数据，而不仅是策略名称或 payload。即使正文展示相同，来源快照、地址映射或呈现元数据不同，仍是不同的完整视图数据。

present_file 应在最终抬头、payload 与 render_spec 全部形成后计算身份，不能沿用尚未加入抬头的基础视图 ID。当前实现已按此规则计算身份。

## 呈现接口

### render_blocks

```python
def render_blocks(blocks: Sequence[Block],
                  strategy: AgentIdStrategy,
                  annotator: Annotator) -> tuple[str, ReferenceMap]
```

```text
agent_id[i] = strategy(blocks[i], i)
payload = concat(annotator(agent_id[i], blocks[i].content))
```

结果映射只覆盖传入的块序列。空序列得到空 payload 与空映射。

可以传入快照的块子集，例如渲染受影响块。子集会从 0 重新计算 index，因此只有在策略不依赖 index，或使用了与完整视图一致的原位置上下文时，才保证子集结果与完整视图对应片段一致。直接对块子集使用 line_number 会重新编号。

### present

```python
def present(snapshot: DocumentSnapshot,
            strategy: AgentIdStrategy,
            annotator: Annotator) -> AgentView
```

Presenter 读取快照，组合策略与标注形式，生成完整 AgentView。payload 按全部 blocks 的顺序生成，reference_map 覆盖全部块，snapshot_id 为输入快照的 id。空快照对应空 payload 与空映射。

呈现不修改快照，不执行文件读写；在确定组件下，最终数据与内容哈希均可重复。

### present_file

```python
def present_file(snapshot: DocumentSnapshot, filename: str,
                 prefix: str | None = None,
                 annotator: Annotator | None = None,
                 strategy: AgentIdStrategy | None = None,
                 label: str = "File") -> AgentView
```

在完整视图前加入展示抬头，并可为块地址增加命名空间。filename 只是展示名称，不触发文件读取。

| 配置 | 行为 |
|---|---|
| annotator 未指定 | 使用 xml_ish |
| strategy 显式指定 | 使用该策略，prefix 不参与地址生成 |
| strategy 未指定，prefix 为非空字符串 | 使用 prefixed_blockkey(prefix) |
| strategy 未指定，prefix 为 None 或空字符串 | 使用 blockkey_as_is |
| label | 抬头用词，默认为 File；非文件对象可用 Text |

payload 为抬头加完整块展示；reference_map 与对应的基础视图相同。空快照仍有抬头。

一次对话呈现多个单元时，不同且适当选择的 prefix 可以区分各单元中相同的块 key，例如 `c0:b1` 与 `c1:b1`。命名空间的选择与避免跨单元地址冲突由调用方负责；显式策略覆盖 prefix 后，也由调用方保证所需的地址区分。

### file_header

```python
def file_header(label: str, filename: str) -> str
```

返回 `"--- [{label}: {filename}] ---\n"`。它只生成展示抬头，label 不改变块地址规则。

## 参考策略与标注形式

### ID 策略

| 策略 | 结果 | 依赖与有效范围 |
|---|---|---|
| `blockkey_as_is` | block.key | 与序列位置无关 |
| `prefixed_blockkey(prefix)` | `<prefix>:<BlockKey>` | 与位置无关；prefix 由调用方配置 |
| `line_number` | `str(index + 1)` | 当前传入序列的块序号，位置性地址 |
| `numkey` | 当前实现为 `str(int(block.key[1:]))` | 针对当前 bN 编号约定的专用策略，与位置无关 |

line_number 与按行分区配套时可用作行号锚。编辑后若一个块包含多行，它仍只占一个块序号，因此不能始终解释为当前正文的物理行号。

numkey 保持已有块的编号，不随插入、删除导致的位置变化而重排。它依赖 key 格式，是专用策略的约定，不赋予通用 BlockKey 必须含数字的语义，也不承诺跨快照分支的全局身份。

### 标注形式

| 标注形式 | 行为 |
|---|---|
| `xml_ish` | 使用带 ID 的开标签与闭标签包裹 content；原内容不转义，标签与内容之间加入换行 |
| `cat_n` | 生成 `<agent_id>: <content>`；结果未以换行结束时补一个换行 |
| `plain` | 忽略 agent_id，原样返回 content |

xml_ish 是故意非良构的 XML 风格标注，开标签以字面反斜杠加大于号结尾。cat_n 与按行分区配套使用时，块中已有的行终止符由 content 自身保留。

## 策略与 partition 的配套

策略对 attrs 的依赖构成与 partition 实现的配套关系。IR 不感知 ID 策略，partition 不感知 Agent 地址；装配层负责选择相互兼容的 partition、策略与标注形式。

例如，未来 Markdown 专用分区器可以写入标题结构，配套策略据此产生 `title1-paragraph1` 式地址。当前没有这套专用实现；通用 Presenter 不解释这些结构字段。

已有实验和工具的具体配套保留在 [00 的装配章节](00-overview.md#已有视图组件配套)，本篇定义组件自身的输入、输出与依赖。

## 有效范围与重新呈现

- 完整 AgentView 对应其 snapshot_id 标明的快照，以及产生它的策略、标注和展示配置。
- 来源完整状态改变，或呈现配置改变后，应重新呈现，不能把旧映射直接当作新状态的映射使用。
- 编辑执行后完整状态与 ID 均未改变、配置也相同时，不因执行过操作而自动失效。相同完整视图数据复用相同 ID。
- 即使某个策略下已有块的 Agent 地址保持稳定，也不能据此认定整份旧 View 仍代表新快照。
- ReferenceMap 本身不保存 snapshot_id，不自动验证是否过期。调用方负责关联来源快照和配置，使用过期地址属于调用方错误。

## 工程约束与当前实现

### 确定性与视图身份

消费变换沿用 05 的纯函数、只读契约。给定确定的策略和标注形式，相同输入应产生相同的 payload 与地址映射。

present 与 present_file 均对最终视图数据计算内容哈希，使用 v- 前缀和 16 位十六进制身份。同一输入得到包含相同 view_id 的完整 AgentView；present_file 在加入抬头与元数据后重新计算。实施记录见[清理计划](../../plan/design-cleanup.md#viewid-内容哈希)。

### 只读与校验

- View、AgentView 和 ReferenceMap 使用 frozen dataclass，但 forward、render_spec 及其嵌套值仍可变；调用方按只读对象使用。
- ReferenceMap 构造时建立反向索引。不得原位修改 forward，否则可能使双向查询不一致；as_dict 返回独立的正向映射副本。
- render_blocks 拒绝重复 AgentBlockId，ReferenceMap 构造拒绝多个 Agent 地址映射到相同 BlockKey，均抛出 ViewError。
- ReferenceMap 构造不接受来源快照参数，不能自行检查是否覆盖快照全部块；完整覆盖由 present 的生成流程保证。
- 当前未完整校验策略返回值类型或组件的纯函数行为；策略、标注形式自身抛出的异常也不会全部包装为 ViewError。

## 验收条件

对合法快照以及符合契约的策略、标注形式：

```text
view.snapshot_id == snapshot.id
view.reference_map 的值集合 == snapshot.blocks 的 key 集合
view.reference_map 为双射
每个 key 经 agent_id_of 再经 key_of 查询，回到原 key
相同输入与配置重复呈现，payload 与地址映射相同
present 对空快照生成空 payload 与空映射
对不依赖序列下标的策略，子集渲染与完整视图对应片段一致
呈现前后，输入快照不变
```

实现应满足：相同输入与配置重复呈现，包含 view_id 在内的完整 AgentView 相等；view_id 与本篇定义的最终视图数据哈希一致。带抬头的视图按最终数据计算身份。相关回归测试验证这些条件。

## 边界

- 不定义 patch 方言、解析与降解（见 `07-agent-api.md`）。
- 完整呈现接口 present 与 present_file 只返回 AgentView，不承担其他文档格式的导出。render_blocks 与 file_header 是生成展示片段、映射和抬头的辅助接口。
- 不落盘，不管理快照历史或当前指针；消费变换与文件读写的职责分工沿用 05。
- 不编辑快照，不把展示标注写回正文。快照是权威状态，视图及映射均为派生物。

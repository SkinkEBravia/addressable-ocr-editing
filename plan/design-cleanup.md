# 设计清理与实现计划

## 范围

以 Design 契约为依据，逐层清理文档、死代码与重复逻辑。先记录改动和实现缺口，再启动代码修改；保留已有实验配置、磁带和兼容行为。

前期仅整理文档。2026-10-19 起，用户已授权修复已知问题、整理接口，并最后迁移 LiteLLM；真实测试仅使用 DeepSeek 小规模调用。进展与验证记录见[本轮执行记录](known-fixes-execution.md)。

## 00–05 基础层审计

[死代码与注释审计清单](audit-design-00-05.md)已于 2026-10-17 完成，仅以当前 Design 00-overview 与 01–05 为设计依据。确认一处未使用导入，未发现可直接删除的函数、类或模块；另列编号逻辑简化候选及旧注释清单。相关 6 个测试文件共 134 项通过。

审计阶段未改源码；2026-10-19 已按授权完成 DC01、CM01–CM09、TS01／TS02，以及确认未使用的上层导入。严格分区、Append、ViewId、编辑回执与 LiteLLM 分别按下方契约实施；RF01 保留，不新增编号抽象。

## 设计变更记录

| 编号 | 设计依据 | 变更 | 状态 |
|---|---|---|---|
| D01 | [01：默认解码策略](../Docs/Design/01-ingestion.md#默认解码策略当前实现) | 明确当前 BOM／UTF-8 策略、BOM 与编码分开保存、往返等式的定义域 | 文档已更新；对应实现已有 |
| D02 | [01：扩展解码策略](../Docs/Design/01-ingestion.md#扩展解码策略未来设计当前不实现) | 未来按文件扩展名选择对应解码器，无对应解码器时采用默认策略 | 仅记录未来设计；当前不实现，不纳入本轮代码清理 |
| D03 | [02：严格分区契约](../Docs/Design/02-partition.md#partitionresult) | 拼接等式、非空块、空文本对应空块序列同时成立 | 已实现 birth 完整入口校验，并补充非法空块回归 |
| D04 | [02：参考分区与持久化](../Docs/Design/02-partition.md#参考实现按字符切分) | 明确位置为分区时输入的 `SourceText.text` 中的位置，以及字符索引单位、attrs 有效时点、JSON 结构转换、保留键与专用策略消费边界 | 文档已更新；不新增元数据更新或分区功能 |
| D05 | [00：输入链路](../Docs/Design/00-overview.md#输入链路)、[05：出生接口](../Docs/Design/05-ir-io.md#出生接口) | 同步完整严格分区要求，标明当前实现缺口 | 文档已更新 |
| D06 | [03：数据结构](../Docs/Design/03-ir-data.md#定义)、[编号分配状态](../Docs/Design/03-ir-data.md#key_cursor编号分配状态) | 明确单文件序列状态、内容寻址的 SnapshotId、当前 bN 规则及恢复旧状态后的编号作用域 | 文档已更新；数据结构、编号与哈希算法保持现状 |
| D07 | [03：序列化](../Docs/Design/03-ir-data.md#序列化) | 定义逻辑 JSON、序列化接口、版本行为、验收条件及当前校验范围；物理存储留在 05 | 文档已更新；未修改序列化或存储代码 |
| D08 | [03：只读约束](../Docs/Design/03-ir-data.md#只读约束) | 保留快照只读契约，注明 frozen dataclass 和元数据引用未提供深层不可变隔离 | 文档已更新；后续方案待评估 |
| D09 | [03：定义](../Docs/Design/03-ir-data.md#定义)、[字段语义](../Docs/Design/03-ir-data.md#字段语义) | 按顺序阅读重排：先定义 DocumentSnapshot 和 Block，再解释字段、序列化及工程约束；移除对后续操作与存储组件的提前展开 | 文档已更新；仅调整文档组织与表述 |
| D10 | [04：Append](../Docs/Design/04-ir-ops.md#append) | 新增块接口直接接收 BlockDraft，统一内容与 attrs 的载体；允许新增空内容块，不扩大初始严格分区的非空约束 | 已改为 draft: BlockDraftLike；上层使用 BlockDraft，调用方与测试已迁移 |
| D11 | [04：定义](../Docs/Design/04-ir-ops.md#定义)、[apply](../Docs/Design/04-ir-ops.md#apply)、[错误](../Docs/Design/04-ir-ops.md#错误) | 定义下说明讨论范围；明确操作顺序、原子性、编号变化、doc_attrs 不变、内容 ID 与错误边界；回滚留在 05，复杂操作降解留在 07 | 文档已更新；除 D10 外沿用现有行为，不修改代码 |
| D12 | [05：定义](../Docs/Design/05-ir-io.md#定义)、[重建接口](../Docs/Design/05-ir-io.md#重建接口)、[存储接口](../Docs/Design/05-ir-io.md#存储接口) | 分开出生、重建与存储职责，定义来源元数据，说明重建回退、Store 初始化及指针行为；修正验收调用 | 严格分区入口已实现；其余维持文档所述行为 |
| D13 | [05：物理格式](../Docs/Design/05-ir-io.md#物理格式)、[工程约束与当前实现](../Docs/Design/05-ir-io.md#工程约束与当前实现) | 修正快照 ID 来源、块去重条件、16 位引用及实际清单示例；明确校验范围、异常及单文件写入保证 | 文档已更新；哈希、存储格式及代码行为均未修改 |
| D14 | [05：快照与消费方的职责](../Docs/Design/05-ir-io.md#快照与消费方的职责) | 保留快照作为统一数据接口的分工：出生与存储管理快照，外部消费方定义输出方式；重建属于独立消费模块 | 文档已补回职责说明；不增加专用输出接口或修改代码 |
| D15 | [03：DocumentSnapshot](../Docs/Design/03-ir-data.md#documentsnapshot)、[05：消费职责](../Docs/Design/05-ir-io.md#快照与消费方的职责)、[旧总览](../Docs/Design/00-dataflow.md)、[文档层概念](../Docs/Concepts/03-document-layer.md) | 审计后补回快照的权威状态与消费变换的纯函数契约；旧总览标为历史；概念页同步 Append 的块坯输入 | 四项文档修复已完成；不改变源码、测试或已记录的待实现状态 |
| D16 | [06：定义](../Docs/Design/06-view.md#定义)、[字段语义](../Docs/Design/06-view.md#字段语义)、[呈现接口](../Docs/Design/06-view.md#呈现接口)、[边界](../Docs/Design/06-view.md#边界) | 保留原范围与边界职责，补全 AgentView／ReferenceMap 的实际数据结构和辅助接口；明确子集下标、plain、编号策略和有效范围 | 文档已更新；不改变代码；原仅输出 AgentView 的约束限定于完整呈现接口，辅助函数按实际返回值说明 |
| D17 | [06：确定性与视图身份](../Docs/Design/06-view.md#确定性与视图身份)、[00：已有配套](../Docs/Design/00-overview.md#已有视图组件配套)、[View 概念](../Docs/Concepts/04-view.md) | 标明 uuid4 导致完整 View 不满足严格纯函数契约；配套表移入装配章节；概念定义兼容无标注展示 | 文档已更新；身份哈希方案现已由 D18 确定，运行逻辑与历史实验配置未改 |
| D18 | [06：ViewId 的计算](../Docs/Design/06-view.md#viewid-的计算)、[AgentView](../Docs/Design/06-view.md#agentview) | 按排除 view_id 后的最终视图数据计算内容哈希；明确 AgentView 可无标注、正文与原文相同以支持 rewrite 对照 | 已实现最终视图内容哈希，并验证相同输入、来源、抬头与映射的身份规则 |
| D19 | [07：范围](../Docs/Design/07-agent-api.md#范围)、[定义](../Docs/Design/07-agent-api.md#定义)、[应用策略](../Docs/Design/07-agent-api.md#应用策略可替换件)、[边界](../Docs/Design/07-agent-api.md#边界) | 保留操作面与入口分工，先定义类型再说明解析／降解／应用；修正 tuple、回执顺序与地址来源、plain、默认组件、CLI 和未来 MCP 的实现状态 | 文档已更新；运行逻辑与测试未改，不新增解析器插件、CLI 参数或 MCP |
| D20 | [07：回执与提交顺序](../Docs/Design/07-agent-api.md#回执生成与提交顺序)、[属性模式差异](../Docs/Design/07-agent-api.md#属性累计) | 记录已复现的保存后回执 KeyError，以及 atomic／best_effort 对 set_attrs 后 move 的不同结果 | 回执已在提交前构建；按用户确认统一累计属性，更新后移动、删除与合并均有回归 |
| D21 | [08：LiteLLM 接入方案](../Docs/Design/08-llm.md#litellm-接入方案)、[当前实现](../Docs/Design/08-llm.md#当前实现与迁移状态) | 确定使用 LiteLLM Python SDK；保留项目配置与统一接口，将协议调用交给库；记录参数、usage、错误、重试及磁带兼容要求 | 已锁定 LiteLLM 1.106.0 并迁移；三协议离线验收，DeepSeek 小规模真实流式复核通过 |
| D22 | [08：输入输出接口](../Docs/Design/08-llm.md#输入输出接口)、[替换约定](../Docs/Design/08-llm.md#替换时保持的约定) | 将构造配置、聊天记录、观察回调、统一结果及失败出口前置，明确替换不变量；旧错误映射、退避细节与日志作为实现参考 | 输入输出接口保持独立；统一 Failure 与 SDK 封装已实施，不复刻旧内部实现 |

## 严格分区入口校验

2026-10-19 已实现，执行与验证见本轮执行记录。

### 契约与责任

| 条件 | 依据 | 当前状态 |
|---|---|---|
| 按序拼接所有块内容等于输入文本 | [02](../Docs/Design/02-partition.md#partitionresult) | `birth` 已检查 |
| 每个 `BlockDraft.content` 非空 | [严格分区概念](../Docs/Concepts/02-partition.md)、[02](../Docs/Design/02-partition.md#partitionresult) | `birth` 已拒绝所有空内容块 |
| 空输入只有空块序列这一种合法分区 | [02](../Docs/Design/02-partition.md#partitionresult) | `birth` 已只接受空块序列 |

校验边界为 `ir.birth(source, result)`，使用现有 `PartitionError`；不增加核心操作或新分区策略。空文本条件可由拼接等式与非空块条件共同保证，无需重复设置等价校验。

非空块约束只用于初始分区／birth 入口，不改变后续 `SetContent`、Block 数据结构或历史快照加载规则。

### 执行清单

- [x] 在 `src/ir/birth.py` 补充空内容块拒绝逻辑，失败发生在初始快照产生前。
- [x] 验证非空原文中夹带空块、空原文配一个或多个空块均抛出 `PartitionError`。
- [x] 验证空原文配空序列、合法 chars／lines 分区、包含换行符的空白行仍被接受。
- [x] 保留拼接不相等与保留 `source` 键的现有拒绝行为。
- [x] 运行相关分区、出生、重建测试，确认未编辑文件的字节级往返保持不变。
- [x] 已更新 00／02／05 中的实现状态和本计划。

## Append 块坯接口调整

2026-10-19 已实现，执行与验证见本轮执行记录。

### 目标与边界

依据 [04：Append](../Docs/Design/04-ir-ops.md#append)，将核心操作的接口从：

```python
Append(draft_content: str, draft_attrs: Attrs, at: BlockKey = HEAD)
```

调整为：

```python
Append(draft: BlockDraft, at: BlockKey = HEAD)
```

- 复用 02 已定义的块坯契约，不在操作接口中再次拆分 content 与 attrs，不新增同形数据结构。
- 实施时核对 `partition` 的公开 `BlockDraft` 与 `ir.birth` 已有的 `BlockDraftLike` 结构性输入边界，避免为了接收块坯依赖其他模块的内部实现。
- 新块仍由 IR 分配 key；锚点、插入顺序、游标、内容 ID 和错误行为保持原有语义。
- `draft.content` 允许为空；严格分区入口的非空校验仍只约束初始分区。
- 保留现有 attrs 顶层复制行为及 03 的只读约束，不借此引入深层不可变容器。

### 执行清单

- [x] 同步 `Docs/Concepts/03-document-layer.md` 的 Append 定义为 BlockDraft 输入，与 04 的目标接口一致；代码迁移亦已完成。
- [x] 调整 `src/ir/ops.py` 的 Append 字段及 `apply` 模式匹配，改为读取 `draft.content`／`draft.attrs`。
- [x] 迁移 `src/surface/degrade.py` 中 append、move 的核心操作构造，以及 `src/surface/errors.py` 中的匹配与错误序列化；核对既有错误输出和磁带兼容行为。
- [x] 迁移 `src/agent/sequential.py`、`src/agent/swe_edit.py` 的新增块调用，并检索源码和测试中的全部核心 Append 构造及字段访问。
- [x] 区分同名的 SurfaceOp Append，保留其已有 Agent 接口与方言，不将其一并改成核心操作接口。
- [x] 更新相关 IR、surface 和 Agent 测试的构造方式，验证新增空内容块、锚点顺序、批次原子性、attrs 顶层复制，以及等价输入的 key／游标／SnapshotId 保持一致。
- [x] 已更新 04 的实现状态与本计划。

## 03 相关代码整理候选

本节旧注释已同步；编号去重保留原实现，其他候选尚未实施。

| 项目 | 对照现状 | 后续处理 |
|---|---|---|
| 旧注释 | types.py 与 ops.py 的身份、游标和编号作用域旧表述已同步 | 已完成，不改变编号或哈希行为 |
| 编号规则重复 | `birth` 直接生成 bN，`alloc` 提供相同编号规则 | 已评估并保留短逻辑；不新增分配策略抽象 |
| attrs 引用可变 | frozen dataclass 只限制字段赋值；嵌套元数据及 `snapshot_to_dict` 返回值可能共享引用 | 单独评估保护方式与代价，先维持只读使用约束，不直接引入深拷贝或新容器 |
| 快照校验范围 | `snapshot_from_dict` 未完整检查类型、游标或内容 ID；Store 有独立加载路径 | 先确认需要加强的契约及入口，再提出代码方案；本项不等同于已确定实施的严格分区入口校验 |
| 05 的 SnapshotId 描述 | 原文误写物理清单哈希，现已与 03 和实现同步为完整逻辑快照（不含 id）计算 | 文档修正已完成；无需修改现有哈希或磁带兼容行为 |

04 的复杂操作说明已从本篇移除，其实际语义由 07 的操作表及链式内容规则承接。`src/surface/degrade.py` 的模块注释已从 04 的旧降解章节改为引用 07；不改变降解行为。

本轮继续以单文件 OCR 修复为范围。多文件、tree、commit 模型及 Git 后端扩展均搁置，不作为当前清理的架构预留任务。

## 05 相关代码整理候选

本节存储与重建注释已同步；未增加校验、异常回退、事务或并发功能。

| 项目 | 对照现状 | 后续处理 |
|---|---|---|
| 存储注释 | 已注明 16 位引用、内容与 attrs 共同参与去重 | 已完成，不更改文件名、引用算法或存储格式 |
| 重建注释与章节引用 | 已注明字段回退范围、非法十六进制 BOM 的 ValueError 与消费职责 | 已完成，不改变异常行为 |
| Store 校验与错误边界 | 加载不复用逻辑反序列化检查；保存信任传入 ID，已有文件不核验内容；部分异常原样传播 | 与 03 的校验候选一并评估后提出方案，不把完整性校验或统一异常包装视为已实现或已确定新增的功能 |
| 写入保证 | 当前按单个文件替换，无跨文件事务或并发写协调 | 文档已说明实际范围；本轮不扩展事务、恢复或并发机制 |

## ViewId 内容哈希

依据 [06：ViewId 的计算](../Docs/Design/06-view.md#viewid-的计算)，身份规则与哈希实现均已完成。

### 目标与边界

- 对最终视图的逻辑数据计算规范化 JSON 的 SHA-256，取前 16 位十六进制字符并加 `v-` 前缀。
- 普通 View 包含 snapshot_id、payload、render_spec；AgentView 另包含 reference_map 的正向字典。
- 排除 view_id 自身及反向映射缓存，避免循环依赖和重复表示。
- present_file 须在最终抬头与元数据加入后计算身份，不复用基础视图的 ID。
- 保留无标注 AgentView：plain 的正文展示与输入正文相同，地址映射可存在但不强制用于 rewrite。
- 按用户要求，`src/view/types.py` 与 `src/view/present.py` 的相关注释已同步；当前已使用最终视图内容哈希。

### 执行清单

- [x] 写明最终视图哈希契约及 plain／rewrite 的合法性，同步 AgentView、Annotator 与 Presenter 相关注释。
- [x] 在 view 模块实现明确字段的逻辑数据转换和哈希计算，不直接序列化 dataclass、函数或反向索引。
- [x] 调整 present 的身份生成，替换 uuid4；调整 present_file，在最终输出形成后计算身份。
- [x] 更新 `tests/test_view.py` 中重复呈现必须产生不同 ViewId 的旧断言，验证相同完整数据得到相同 ViewId、不同来源／展示／元数据／映射参与身份计算、字典键顺序不影响结果。
- [x] 验证抬头加入后的身份与最终视图一致，以及 plain 展示和映射行为保持不变。
- [x] 核对现有调用方是否将 ViewId 作为每次调用的事件编号，保留历史 UUID 记录的可读性，不修改 SnapshotId 或已保存磁带。
- [x] 已更新 06 的 uuid4 实现状态及本计划。

## 06 实现差异与代码整理候选

ViewId 哈希已实现；下表其余候选按实际范围记录，不自动扩展实现。

| 项目 | 对照现状 | 后续处理 |
|---|---|---|
| 消费变换纯函数与 ViewId | `render_blocks` 在确定组件下生成确定的展示和映射；`present` 已对最终数据取内容哈希，完整返回对象可重复 | 已按上节最终视图内容哈希方案实施；不删除已有 ViewId 字段 |
| 可变映射与呈现元数据 | frozen dataclass 不冻结 forward／render_spec；ReferenceMap 缓存反向映射，原位修改 forward 会造成不一致 | 当前明确只读契约，后续与 03 的元数据保护候选一起评估，不自动引入深拷贝或新容器 |
| 子集渲染与位置策略 | `render_blocks` 从 0 枚举传入序列，line_number 在子集中重新编号 | 已修正文档适用条件，不把保持原始位置写成当前保证；不增加原位置参数或改动编号行为 |
| 类型及接口注释 | `src/view/types.py` 已允许无标注展示；`src/view/present.py` 已实现并注明内容哈希 | 注释与哈希实现已同步；组件名称、类型校验与错误包装候选仍需另行评估 |
| 有效范围 | ReferenceMap 无来源快照字段，也不校验过期；render_spec 只保存组件名称及部分展示配置 | 维持调用方关联来源与配置的职责，不借清理新增过期检查或策略重建机制 |

原 06 的范围段落完整保留；边界中的 patch 方言／解析／降解、完整呈现只输出 AgentView 与不落盘职责均已保留。原五项实验配套已迁入 00 装配章节，不删除工具或实验信息。

## 07 回执构建与提交顺序

依据 [07 的已知问题](../Docs/Design/07-agent-api.md#回执生成与提交顺序)，2026-10-19 已修复，以下保留原复现与执行清单。

### 复现与目标

初始按行分区文本为 `aa\nbb\ncc\n`，执行：

```text
replace(b1, "a", "A")
move(b1, b2)
```

修复前，结果快照已经保存，b1 被替换为新 key，但 `_affected` 仍按 updated 状态查询旧 b1，抛出 KeyError。不能把这类已提交后的错误描述成已有状态完全不变。

修复目标是合法编辑产生正确、完整的回执；atomic 路径在保存之前完成回执构建与可返回性检查。文件写入失败仍遵守 05 的实际保证，不在本项扩展为跨文件事务。

### 执行清单

- [x] 修正 `src/surface/patch.py` 的 `_plan`／`_affected`，结合最终块状态处理先更新后移动等组合，不查询已经消失且未明确报告删除的旧 key。
- [x] 明确同一块连续更新、移动或删除后的回执归并，保持单独 move 产生新身份、删除回执使用旧地址、现存块按新序排列等已有规则。
- [x] 调整 atomic 路径，先形成有效的结果快照和回执，再调用 save；不新增持久化事务或更改 best_effort 逐条保存的模式语义。
- [x] 增加回归验证：replace／set_content 后 move 能返回正确回执；回执或 Annotator 在 atomic 提交前失败时 current 与已保存数据不变；best_effort 的已提交范围与回执可核对。
- [x] 保留解析／降解／核心语义错误的来源定位，以及两个模式已有的成功内容链式叠加行为。
- [x] 已同步 `src/surface/patch.py` 的旧原子性注释、07 的实现状态与本计划。

## 07 模式语义与整理候选

以下区分已完成修复与尚未启动的扩展候选。

| 项目 | 当前状态 | 后续处理 |
|---|---|---|
| 属性累计与 move | 两模式都读取之前成功操作累计后的 attrs，set_attrs 后 move 保留新属性 | 已按用户确认实现，并覆盖两种模式回归 |
| 回执分配器耦合 | `_plan` 依赖 bN 与输入 key_cursor 推导新 key | 作为回执整理候选评估，保持当前编号与磁带兼容，不新增分配策略或受控编辑架构 |
| 旧回执注释 | 已修正 plain 合法性与阶段失败边界注释 | 已同步；保留现有错误序列化字段名 |
| 方言替换接入 | 当前 run_patch 固定调用 fn parse | 文档已区分职责设计与实现，不新增解析器注入、注册或插件接口 |
| CLI 默认值与参数 | 文件 CLI 只支持 chars／stdin／atomic，实验工具可用 lines 和 best_effort；当前没有 doc 可执行入口 | 已修正文档，不在清理中统一不同入口的默认值或添加命令参数 |
| MCP | 当前无 serve 接口、子命令或服务实现 | 保留未来设计、会话复用语义及 loopback 约束，本轮不实现 MCP、鉴权、TLS 或并发机制 |

原 07 的入口定位、七种 SurfaceOp、错误溯源、默认组件及 fn 语法、CLI 输出与退出码、未来 MCP 会话／传输边界均保留；无条件回滚、XML 永不混淆和预检免费等表述已按现状纠正。

## LiteLLM 客户端迁移

依据 [08：LiteLLM 接入方案](../Docs/Design/08-llm.md#litellm-接入方案)，采用进程内 Python SDK。2026-10-19 已完成替换；最后实施本项，基础层和编辑修复先完成。

### 目标与边界

- 保留 LLMClient、build_client、ModelConfig、Message、Completion、Usage、Failure 及现有 TOML；上层不接触 LiteLLM 类型。
- 使用 LiteLLM 的 completion／responses 入口接入原有三协议，不部署 Proxy，不新增协议或 agent 功能。
- 项目保留必要的配置校验、凭证解析、结果与错误转换；不再自行维护完整 HTTP／SSE 客户端。
- 以 08 开头的输入输出接口为迁移首要验收依据；旧错误映射、退避细节和调试日志用于核对，不要求逐条复刻。上层依赖的失败记录能力仍需兼容。
- 保持实验参数和服务端 token 统计口径；旧磁带保持可读。迁移会改变依赖与运行实现，不并入 00–05 的死代码清理批次。

### 执行清单

- [x] 在 08 写明 LiteLLM 架构、职责、兼容要求与实际实施状态。
- [x] 锁定 LiteLLM 1.106.0（该版本 Responses 导入需要 mcp extra）与 Tenacity，更新 pyproject.toml 与锁文件。
- [x] 先用离线请求捕获核对三协议的实际 URL、模型名称、system／历史消息、输出上限、推理参数及 extra_body 合并；保留未知键、缺凭证、anthropic 参数限制的请求前检查。
- [x] 明确单一重试预算及底层 SDK 配置，核对 HTTP 429／5xx／断连、408／409 等分类对调用方的影响，保留实际尝试次数和耗时；关闭 SDK 自动重试，由 Tenacity 对含流式消费的完整尝试执行唯一预算；不复刻旧传输实现。
- [x] 实现统一结果与 Failure 转换，核对服务端 token、缓存及推理 token、usage 缺失、raw 响应来源和序列化兼容；不启用本地用量估算、自动换模型、缓存或历史改写。
- [x] 验证流式与非流式的回答及结束状态，处理部分文本后断连、流式错误事件、空文本、停滞与观察回调；覆盖已复现的吞异常缺陷。
- [x] 核对库能提供的重试与流式观察信息，再调整项目日志及必要的停滞保护，不提前承诺完整事件分布或底层原始响应均可获得。
- [x] 调整相关离线测试，验证报告、Session 磁带及 resume／replay 兼容；真实端点按授权仅使用 DeepSeek 小规模调用，结果见执行记录。
- [x] 验证完成后替换旧客户端，再按实际引用移除自建适配器、传输代码及失效测试；不提前按文件名整包删除。
- [x] 更新 08、实现现状及本计划，记录兼容处理与实际验证范围。

## 后续清理候选

未使用导入已完成；其余项为尚未启动的候选，不自动扩大本轮范围。

| 项目 | 检查／清理对象 | 状态 |
|---|---|---|
| 未使用导入 | `agent/loop.py`、`swe_bash.py`、`swe_edit.py` 的 `DONE`；`agent/toolset.py` 的 `field`；`ir/store.py` 的 `Attrs`；`view/defaults.py` 的 `Annotator` | 已复核并移除 |
| 重复调用解析 | `agent/standard.py`、`numkey.py`、`swe_edit.py` 的逐行调用和末尾 done 处理 | 待提出具体合并方案；保留方言、错误与调用顺序差异 |
| 重复 IR 初始化与 flush | numkey 与 swe-edit 的创建 Store／分区／birth／save 及轮末持久化 | 待提出具体合并方案；不改变普通 patch 的保存节奏 |
| 后续设计审阅 | 09–11 的职责边界与当前实现 | 03–07 文档已整理；08 已完成迁移，其余逐篇审阅后记录 |

历史工具名承担 resume／replay 兼容职责，不作为死代码删除。扩展名解码器、Markdown 专用分区器和树／图 IR 都是未来功能，不在当前清理范围。

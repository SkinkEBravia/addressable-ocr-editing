# 外部接口：Agent 操作面、CLI 与 MCP

> 前置概念：[View 与 Agent 操作面](../Concepts/04-view.md)；核心错误：[OpError](04-ir-ops.md#operror)；视图：[06-view.md](06-view.md)

## 范围

操作面围绕以下链路工作：

```text
patch 文本 → 解析 → SurfaceOp 序列 → 降解 → 核心操作 → apply → 结果快照 → 受影响块回执
```

库内 Agent 接口、CLI 与 MCP 是同一操作面的三种入口设计。CLI 与 MCP 的主要使用者也可以是外部 Agent，设计上共享方言、错误结构和会话状态语义。当前已实现库内接口与 CLI；MCP 是未来封装，尚未实现。

本篇定义 SurfaceOp、解析与降解、应用策略、回执及入口职责。核心编辑语义归 04，快照存储归 05，视图生成归 06；入口的组件选择属于装配。

## 定义

### SurfaceOp

SurfaceOp 是与文本方言无关的 Agent 编辑操作。

| 公共字段 | 类型 | 含义 |
|---|---|---|
| `position` | `LineSpan` | 操作在 patch 文本中的行号区间 |

`LineSpan = tuple[int, int]`，表示从 1 开始、包含两端的行号区间。当前 fn 方言一行一个调用，因此起止行号相同。

### patch 方言

方言由文本格式与解析器组成。更换方言的职责限定在文本到 SurfaceOp 的转换，不改变核心操作语义。

当前公开的 run_patch 固定调用 fn 解析器，没有解析器注册或注入接口。“换方言只换解析器”是职责约定，不表示现已提供运行时插件机制。

### Origin 与 CoreOpEntry

Origin 将一条核心操作追溯到产生它的 SurfaceOp。

| 字段 | 类型 | 含义 |
|---|---|---|
| `surface_index` | `int` | SurfaceOp 在原批次中的序号，从 0 开始 |
| `position` | `LineSpan` | 该 SurfaceOp 在 patch 文本中的位置 |

```text
CoreOpEntry = tuple[Op, Origin]
```

一个 SurfaceOp 可以展开为多条核心操作；这些条目保留同一来源信息。

### ParseError

ParseError 表示文本未能解析为合法的 SurfaceOp 序列。

| 字段 | 类型 | 含义 |
|---|---|---|
| `line` | `int` | 出错行号，从 1 开始 |
| `reason` | `str` | 解析失败原因 |

### SurfaceError

SurfaceError 表示降解或核心操作执行失败，保留操作面的位置与展开信息。

| 字段 | 类型 | 含义 |
|---|---|---|
| `stage` | `str` | degrade 或 apply |
| `surface_index` | `int` | 原批次中的 SurfaceOp 序号，从 0 开始 |
| `position` | `LineSpan` | 原 patch 的行号区间 |
| `expanded` | `tuple[Op, ...]` | 该 SurfaceOp 展开的核心操作；降解失败时为空 |
| `cause` | `str \| None` | 可供程序判断的原因码，如有 |
| `message` | `str` | 失败说明 |

### PatchResult

PatchResult 是一次 patch 的回执。

| 字段 | 类型 | 含义 |
|---|---|---|
| `snapshot_id` | `SnapshotId` | 结果快照身份，不保证与输入 ID 不同 |
| `affected` | `tuple[AffectedBlock, ...]` | 受影响块的回执 |
| `errors` | `tuple[SurfaceError, ...]` | best_effort 跳过的操作失败记录；成功返回的 atomic 回执恒为空 |

### AffectedBlock

AffectedBlock 描述一个受影响块，供调用方核对结果。

| 字段 | 类型 | 含义 |
|---|---|---|
| `key` | `BlockKey` | 块身份 |
| `agent_id` | `AgentBlockId` | 结果视图中的地址；删除块使用原视图地址 |
| `status` | `str` | appended、updated、moved、merged 或 removed |
| `annotated` | `str \| None` | 使用同一策略与标注形式生成的展示片段，允许无标注；删除块为 None |

## SurfaceOp 标准集

当前提供七种操作：四种核心操作的直译和三种包装。position 是每种操作的公共字段。

| 操作 | 操作字段 | 语义与降解 |
|---|---|---|
| `SetContent` | `id, text` | 按 Agent 地址定位块，整体替换 content |
| `SetAttrs` | `id, attrs` | 整体替换块级 attrs |
| `Append` | `anchor, text, attrs=None` | 在锚点后新增块，由核心层分配 key |
| `Remove` | `id` | 删除对应块 |
| `Move` | `id, anchor` | 删除原块，再于锚点后新增；产生新 key |
| `Merge` | `a, b` | 将 b 的内容拼接到 a 末尾，再删除 b |
| `Replace` | `id, old, new` | 替换块内容中 old 的全部出现处 |

id、anchor、a、b 均使用 AgentBlockId。保留锚点 `HEAD_ID = "HEAD"` 仅能用作 anchor，直接映射为核心层的 `HEAD = "head"`，不经 ReferenceMap 查询，不能作为真实块的目标地址。

核心 Append 已直接接收 BlockDraft，见 04；降解构造块坯，不改变 SurfaceOp 的文本接口。

## 解析与降解

### parse

```python
def parse(patch_text: str) -> tuple[SurfaceOp, ...]
```

解析保留文本顺序和原始行号。当前语法在“方言 fn”中定义；语法错误抛 ParseError。

### degrade

```python
def degrade(surface_ops: tuple[SurfaceOp, ...],
            ref_map: ReferenceMap,
            snapshot: DocumentSnapshot) -> tuple[CoreOpEntry, ...]
```

ReferenceMap 将 AgentBlockId 换回 BlockKey。snapshot 提供内容与块级元数据，供包装操作展开使用；降解本身不修改快照、不落盘。

同一 patch 的地址始终以 patch 前的 View 为准，不能引用本次新增块。新地址通过回执返回，供后续 patch 使用。来源关联由调用方负责，ReferenceMap 不自动校验是否过期。

### 内容与结构规则

按文本顺序累计同一块的内容变化。后面的 replace、merge 读取此前操作产生的内容，move 带走累计内容；set_content 是绝对重置。

包装关系为：

```text
move(k, at)      = Remove(k) + Append(块坯, at)
merge(a, b)      = SetContent(a, 累计内容(a) + 累计内容(b)) + Remove(b)
replace(k, o,n)  = SetContent(k, 累计内容(k).replace(o, n))
```

move 的新 key 与原 key 不同。地址映射仍来自原 View，核心操作在执行时检查目标与锚点是否仍然存在；不能把“内容累计”理解为可以重新寻址已删除或移动的旧身份。

replace 要求 old 存在于当时的累计内容，否则抛出原因码为 PATTERN_NOT_FOUND 的降解错误。多处出现全部替换；只改一处时，调用方可通过更长上下文使匹配唯一。定位以块为单位，内容变化可以小于整块，不要求块必须对应一行。

内容与属性均按成功操作的顺序累计。move 带走当前累计的 content 与 attrs；atomic 与 best_effort 使用相同的属性累计语义。

## 方言 fn

一行一个函数调用：

```text
set_content(b3, "替换后的块全文")
set_attrs(b3, {"start": 120})
append(b2, "新块内容")
append(HEAD, "文首新块", {"kind": "intro"})
remove(b4)
move(b1, b5)
merge(b1, b2)
replace(b3, "teh", "the")
```

- 参数均为位置参数。
- 地址可以是裸标识符或 JSON 字符串，b3 与 `"b3"` 等价。纯数字地址等不符合裸标识符形式的地址须用字符串表示。
- text、old、new 必须是 JSON 字符串，attrs 必须是 JSON 对象。换行通过字符串中的 `\n` 转义表达，不把一次调用拆成多行。
- 空行和去除前导空白后以 # 开头的行忽略。
- 整段 patch 先完成语法解析，再按所选应用模式处理；不是每种模式都将全部操作一次性 apply。

## 库内接口

```python
def run_patch(store: Store, patch_text: str,
              strategy: AgentIdStrategy, annotator: Annotator,
              *, mode: str = "atomic") -> PatchResult
```

run_patch 负责加载当前快照、解析、建立地址映射、降解、应用、保存和生成回执，是有存储副作用的装配接口。调用方应使用与此前展示一致的策略和标注形式。

### 应用策略（可替换件）

| mode | 当前执行方式 | 失败处理 |
|---|---|---|
| `atomic` | 全批降解，核心操作一次性 apply，成功后 save | 解析、降解或核心语义失败时不提交；返回回执的后续失败另见已知问题 |
| `best_effort` | 每条 SurfaceOp 分别 degrade、apply、save | 跳过捕获的 SurfaceError／OpError，记入 errors；保留其他成功操作 |

best_effort 跳过的是一条 SurfaceOp。move 等包装展开的多条核心操作仍由一次 apply 原子执行。所有地址仍来自批次前 View，成功操作之间的内容变化按顺序生效。

语法错误在两种模式下都拒绝整批。I/O、回执构建及其他未包装异常不属于 best_effort 的逐条语义跳过范围。未知 mode 当前抛 ValueError；CLI 当前不暴露 mode 参数。

best_effort 适合相互独立、散布各块的 OCR 修复。需要整批语义成功的结构编辑使用 atomic。两种模式仍须分别说明其读取状态和失败范围，不能假设它们仅在提交粒度上不同。

## 回执与错误回传

### 受影响块

目标是修改后即可核对结果，不必重新获取全量 View。

- 结果中仍存在的受影响块按新文档顺序排列。
- 删除块按旧文档顺序排在最后；agent_id 使用旧地址，annotated 为 None。
- 同一 key 合并为一条回执，当前按最后一次涉及它的操作决定 status；最初出现顺序用于内部收集，不是最终文档排序规则。
- annotated 使用结果视图中的地址和相同 Annotator 生成。使用 plain 时可直接是原内容，不强制加入标注。
- 地址先根据完整结果快照生成，再渲染受影响块，以保持 line_number 等位置策略与下一次完整 View 一致。

move 报告新 key 和 moved 状态。原块在同批次内先修改再移动时，旧 key 被消费，回执只保留最终的新身份。

### 错误回传

```text
ParseError                         → 文本行号与解析原因
OpError → Origin → SurfaceError    → 原 SurfaceOp、文本位置、核心展开与原因
```

- apply 失败时，用 OpError.index 找回 Origin，再包装 SurfaceError。
- cause 在核心执行失败时为 OpError.reason；降解失败通常为 None，replace 匹配失败时为 PATTERN_NOT_FOUND。
- ParseError、SurfaceError、PatchResult 提供 to_dict；输出普通 JSON 数据后再序列化。dataclass 对象本身不能直接交给 json.dumps。
- PatchResult 的 affected、errors 和 SurfaceError 的 expanded 在内存中为 tuple；to_dict 将相应序列转换为 JSON 数组。

apply 是纯函数，可以试跑而不提交结果；试跑仍有计算成本。当前 run_patch 不额外运行一次独立预检，而是使用实际 apply 的成功结果继续保存。

## 默认组件

默认值由入口选择，不属于 surface 的固定语义。

| 入口 | 分区 | 地址与标注 | 应用方式 |
|---|---|---|---|
| 实验 patch 工具配置 | 默认 lines，可选 chars；chars 的 block_size 默认 400 | 默认 blockkey_as_is 与 xml_ish | 默认 atomic，可配置 best_effort |
| 当前文件 CLI | 仅 chars，size 默认 1000 | 固定 blockkey_as_is 与 xml_ish | atomic |

分区接口见 02；ID 策略和标注契约见 06。工具配置与既有实验的配套属于装配，不据此宣称 CLI 也支持相同配置项。

### 标注形式 xml-ish

默认 xml_ish 使用以下展示样式：

```text
<x id="b3"\>
块内容原文，原样不转义
</x>
```

开标签以字面反斜杠加大于号结尾，是故意非良构的 XML 风格标注。块内容不转义，标签周围加入换行，具体生成规则归 06。

非良构不保证任意正文都不会出现相同标记，不能声称可从展示文本无歧义恢复块边界。程序使用快照和 ReferenceMap 进行寻址，不将该展示当作快照的权威序列化。

## CLI 对方言的限制

CLI 是操作面的一个实际调用入口，保留以下分工：

1. patch 文本经 stdin 传入，不经 argv。文件输入通过调用方读取或 shell 重定向后进入 stdin；当前没有独立的 patch 文件参数。
2. patch 命令支持人读文本和 `-f json`；成功回执与已捕获错误通过 to_dict 转换。JSON 错误输出到 stdout，人读错误输出到 stderr。这不是所有命令均支持 format 参数的保证。
3. 当前 CLI 是单发进程，状态通过会话目录共享；调用方串行驱动，不提供并发写协调。

| 退出码 | 已捕获的结果 |
|---|---|
| 0 | 成功 |
| 1 | ParseError |
| 2 | 降解阶段 SurfaceError |
| 3 | apply 阶段 SurfaceError |
| 4 | 已捕获的 I/O 或 Store 错误 |

argparse 的命令用法错误也可能返回 2，不能仅凭退出码判断为降解错误。未捕获异常不保证沿用上述错误结构。

当前入口为 `python -m application`，可通过 uv run 启动；仓库未注册名为 doc 的可执行入口。命令形式为：

```text
python -m application ingest <file> --session <dir> [--partition chars] [--size 1000]
python -m application view --session <dir>
python -m application patch --session <dir> [-f json]
python -m application write --session <dir> [-o <path>]
python -m application rollback <SnapshotId> --session <dir>
```

ingest = read + partition + birth + save，并记录来源路径；view = load + present；patch = run_patch；write = load + reconstruct + write；rollback = set_current。view 命令只调用 06 的生成接口，不承担其呈现语义。

## MCP 服务（未来设计，当前未实现）

保留将同一操作面封装给外部 Agent／harness 的设计。原拟采用 Streamable HTTP 单端点服务，由一个进程持有会话目录：

```python
def serve(session: Path, host: str, port: int) -> None
```

该接口及 serve 子命令当前均不存在，本轮不实现。

- 拟议工具封装 view、patch、write 等应用层操作；patch 内部沿用 SurfaceOp 与错误回传链，不把应用层命令混同为七种 SurfaceOp。
- 设计目标是共享 CLI 的方言、错误结构和会话状态语义，换通道不改变编辑语义。
- 按会话目录持有状态；可与串行运行的 CLI 进程使用同一目录。多会话原拟通过多进程或多端口承载，不在服务内复用。
- 原 v1 设计仅绑定 loopback；鉴权、TLS 等传输扩展不在本轮范围，不构成当前已实现的服务保证。

## 已知问题与实现边界

### 回执生成与提交顺序

atomic 路径在保存前完成结果快照与回执构建。以下组合已覆盖回归：更新后的旧身份被移动消费，回执只报告最终的新身份。

```text
replace(b1, "a", "A")
move(b1, b2)
```

解析、降解、核心语义或候选回执构建失败时，atomic 不保存候选状态；best_effort 保留此前已成功提交的操作，当前候选回执也在保存前构建。I/O 失败沿用 05 的存储保证，不提供跨文件事务。

合法编辑返回完整回执；同一 key 的状态按最后操作归并，move 消费旧 key 并报告新 key，删除使用旧地址。回执归并与提交顺序已修复，见[实施计划](../../plan/design-cleanup.md#07-回执构建与提交顺序)。

### 属性累计

`set_attrs(b1, {"x": 1})` 后再 `move(b1, b2)`，两个模式的新块均携带更新后的 attrs。best_effort 只累计成功操作；失败操作不改变后续状态。

此语义由用户确认并已实现，记录在[模式语义核对计划](../../plan/design-cleanup.md#07-模式语义与整理候选)。受此修复影响的历史实验应在比较时明确版本。

### 其他实现边界

- 回执的新增 key 当前通过输入游标和 bN 规则推导，仍依赖分配器格式；通用解耦目标不能视为已实现。
- ViewError、I/O、非法组件和回执内部错误并未全部包装成 ParseError 或 SurfaceError。
- 当前解析器、默认组件和 CLI 选项以本篇现状为准；MCP 和可替换解析器接入属于设计范围内尚未实现的部分。

## 验收条件

对合法输入和已支持的组件组合，分别核对：

```text
parse 保留操作顺序与原文本行号
degrade 的每条核心操作均能通过 Origin 找回来源 SurfaceOp
atomic 的解析／降解／核心语义失败发生在提交前，已有快照与指针不变
best_effort 的语义失败跳过对应 SurfaceOp，成功操作保留，errors 指向原批次位置
成功返回的 snapshot_id 对应结果快照，不要求一定产生不同 ID
回执的现存块按新文档序排列，删除块按旧文档序排在最后
使用 plain 时回执允许无标注内容
ingest → 无编辑 → write，对合法文件输入逐字节还原
```

已修复的回执组合与提交前构建检查有对应回归。MCP 的验收留在未来实现阶段，不与当前 CLI 验收混写。

## 边界

- 方言、ID 策略、标注形式分别承担文本解析、地址生成和内容呈现，可独立替换；选择与配套由装配层负责。
- 降解与核心执行消费 SurfaceOp，不解释 fn 语法。库内 run_patch 和 CLI 当前通过固定 fn 解析器接入；未来 MCP 复用相同操作契约。
- View 的生成归 06；CLI 的 view 命令只是调用方，不把标注写回正文。
- 并发控制和锁不在当前实现范围；调用方串行使用会话目录。
- 保留 MCP 仅绑定 loopback、鉴权和 TLS 不在原 v1 范围的设计约束，尚未实现服务，本轮不扩展传输功能。

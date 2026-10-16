# 中间表示 · 出生、输出与 Store

> 前置概念：[文档层](../Concepts/03-document-layer.md)、[I/O 边界](../Concepts/01-io-boundary.md)；数据结构：[03-ir-data.md](03-ir-data.md)；迁移：[04-ir-ops.md](04-ir-ops.md)

## 范围

文档层不定义的两端，各由一个接口承担：

- **出生**：`PartitionResult -> DocumentSnapshot`
- **输出**：统一输出接口；重建是其一消费方

外加 store：快照的持久化、当前指针、会话目录。

## 出生接口

```python
def birth(source: SourceText, result: PartitionResult) -> DocumentSnapshot
```

1. **校验契约**：满足 [02 的严格分区契约](02-partition.md#partitionresult)：按序拼接等于原文、每块内容非空、空文本对应空块序列。不符抛出 `PartitionError`（严格分区的验收点在边界，而非信任上游）。当前只实现拼接等式校验，拒绝空内容块的完整入口校验待实现，见[设计清理计划](../../plan/design-cleanup.md#待实现的严格分区入口校验)。
2. **装订 key**：`key_cursor` 从 1 起，按序为每个 `BlockDraft` 分配 `b{cursor}`。
3. **写入文档级数据**：`result.doc_attrs` 原样进入快照 `doc_attrs`；另写入保留键：

   ```json
   "source": { "encoding": "utf-8", "bom": "fffe" }
   ```

   `bom` 为十六进制字符串，无 BOM 时是空串。`"source"` 是保留键，partition 实现不得使用。
4. 生成 `SnapshotId`。

## 统一输出接口

IR 对外的唯一输出是 `DocumentSnapshot` 本身（不可变、JSON 可序列化）。一切输出——重建回 `SourceText`、导出 View、transform 为其他格式——都是消费快照的**外部模块**：

```text
Consumer = DocumentSnapshot -> X   # 纯函数，只读
```

- IR 不为任何输出增设专用接口；消费方自己的配置、方言、格式化规则都归消费方。
- 下文"重建"是第一个标准消费方；View 消费方见 `06-view.md`。

### 消费方：重建

```python
def reconstruct(snapshot: DocumentSnapshot) -> SourceText
```

- `text = concat(b.content for b in blocks)`
- `encoding` / `bom` 从 `doc_attrs["source"]` 取回；缺失时回退 `utf-8` 无 BOM。

配合 sourceio 的 `write`，未编辑的快照写回与原文件逐字节相同。

## Store

### 职责

快照的持久化与指针。store 不认识 op、不解释快照内容。

```python
def save(store, snapshot: DocumentSnapshot) -> SnapshotId
def load(store, snapshot_id: SnapshotId) -> DocumentSnapshot
def current(store) -> SnapshotId
def set_current(store, snapshot_id: SnapshotId) -> None   # rollback 的物理实现
```

### 物理格式：块级内容寻址

```text
<session>/
  blobs/<hash>.json            # {"content": str, "attrs": Attrs}，hash = sha256(规范化 JSON)
  snapshots/<SnapshotId>.json  # 清单，见下
  current                      # 纯文本，内容为当前 SnapshotId
```

快照清单 = [03 定义的逻辑格式](03-ir-data.md#逻辑表示)中，每个块条目的 `content` / `attrs` 替换为引用：

```json
{ "spec": 1, "id": "s-a3f9…", "doc_attrs": { … }, "key_cursor": 3,
  "blocks": [ { "key": "b1", "ref": "<hash>" }, { "key": "b2", "ref": "<hash>" } ] }
```

规则：

- blob 无 key：内容相同的块即使 key 不同也只存一份。
- `SnapshotId` = 清单（不含 `id` 字段）规范化 JSON 的哈希，加 `s-` 前缀。相同清单同 id，天然去重。
- `save` = 写新 blob + 写清单 + 移动 `current`；未修改的快照重复 `save` 不产生新数据。
- `load` = 读清单并按 `ref` 装配 blob，对外恢复为完整 `DocumentSnapshot`——**CAS 是 store 内部实现，IR 接口不感知**。

### 指针与会话

- `current` 是当前指针的唯一落盘形式；`set_current` 重写该文件即完成 RollBack，历史清单与 blob 全部保留（append-only）。
- 会话目录 `<session>` 由装配层创建与初始化；CLI 各进程凭会话目录路径共享同一份状态。
- 不做引用计数与 GC；会话结束由装配层整体清理。

## 验收

```text
reconstruct(birth(source, partition(source))) == source
load(save(store, s)) == s
set_current(store, t) 后 current(store) == t
```

## 边界

- 不定义 op 语义（`04-ir-ops.md`）；`apply` 是纯函数，落盘由调用方驱动。
- 不做增量压缩、不做 GC；保留策略就是全量保留到会话结束。
- View 的生成与持久化不归本模块。

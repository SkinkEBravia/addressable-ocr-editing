# 踩坑记录

按时间序。每条：现象 → 原因 → 教训。

## 1. 同块多 replace 全部丢失（本项目最重的坑）

现象：实验里 system 臂 cMER ≈ noop，patch "成功"但文本没变。
原因：degrade 是静态展开，每条 `replace` 各自基于 patch 前快照生成**整条** `SetContent`；N 条打同一个 key，`apply` last-wins，只有最后一条活下来。模型的 48 条修复丢了 47 条。
教训：`SetContent` last-wins 对"整体替换"语义自洽，对"片段修改"是灾难。凡是从旧状态派生新状态的操作（replace/merge/move 的 draft），批次内必须链式读取累计状态。另外这个 bug 的隐蔽性在于 error=None、failed=False——"成功"地没干活，只有分数能暴露它。

## 2. 把磁带当垃圾删了

现象：修复坑 1 之后，我删掉了 unit3 system 臂的 raw 文件准备"干净重跑"。
原因：混淆了"坏结果"和"坏产物"——磁带里的模型响应是好的，坏的只是本方的 apply 代码。留着就能用修复后的代码重放，零 token 重算。
教训：原始响应是不可再生资产，后处理永远可以重算。删任何东西之前先问：这里面的信息能不能由代码重新导出？（后来据此加了 replay 模式。）

## 3. 以为单元是"一行"，实际是一块

现象：`partition_lines` 分完只有 1 个块，所有 replace 全打在 b1 上。
原因：凭"逐行转写"的印象假设数据结构；实际 icdar2017 的 chunk 中位 1–3k 字符且常无换行。
教训：partition 策略要看数据的真实结构选，先 `len(blocks)` 再谈设计。这个误判的直接收益是暴露了坑 1——块越少，同块多 replace 越容易发生。

## 4. doc 轨空转一轮

现象：按"同一 document_id 拼接大文档"跑的 doc 轨，结果其实还是单元粒度。
原因：没先验证数据假设——比赛数据**每文档只有一个单元**，拼接规则永不生效。那一轮唯一产出是噪声量级（同文本两遍 output_ratio 1.04 → 1.42）。
教训：实验设计里的每条数据假设，先用五分钟脚本验证，再烧 token。

## 5. 思考 token 淹没一切

现象：replace 把可见输出压缩了 2–4×，账单 token 反而更多（有个样本 patch 臂 54k vs 重写臂 28k）。
原因：deepseek-v4-flash 思考模式默认开，`tokens_out` 的 96%+ 是思考；patch 模式逐字匹配 old、验证模式存在性，想得**更多**。
教训：可见文本的压缩优势在思考噪声下无法兑现到账单。token 效率的杠杆在思考预算，不在输出格式。做 A/B 前先看清楚 token 的构成，别拿 tokens_out 当"输出长度"用。

## 6. Python `str.replace` 的多处替换

现象：新写的 3 个链式测试全挂。
原因：`"aaaa".replace("aa", "X") == "XX"`——非重叠、从左到右、**全部**替换，我按"只换第一处"的直觉写了期望。
教训：replace 的语义就是 replace-all，文档、prompt、测试三处都要按这个写。想要唯一替换就引导调用方把 old 取得足够长。

## 7. resume 的两个盲区

现象一：300s 超时杀掉实验，0/3 完成——raw 只在 (sample, arm) **完成后**写盘，长任务中断全白费。
现象二：同名臂换了 prompt 重跑，断点续跑直接跳过——resume 只按 (样本, 臂名) 判断。
教训： checkpoint 粒度要匹配任务时长；resume 的键要包含"用什么配置跑的"，否则探索期必然吃到陈数据。

## 8. 文档落后代码

现象：链式修复、TOML/replay 的实现偏差只写进代码 docstring，design 文档没同步，被 review 抓到。
原因：bugfix 压力下代码先行，事后没有回流检查。
教训：这个项目的 Docs 是宪法。每次提交前加一项检查：实现偏差是否已回流 design。代码 docstring 里写"与 0X 文档的一处偏差"是合法缓冲，但不是终点。

## 9. 报告表格会撒谎

现象：`dev20-doc` 的表格 track 列写着 doc，实际数据还是 icdar2017 单元——看起来像"文档轨结果"，差点据此下结论。
教训：读表先看 subset 和 n，track 标签只是运行参数的回声。把"这次到底跑了什么"（数据路径 + 样本数 + 臂配置）写进 report 才算数——这也是后来配置落盘 `arms.<name>.config` 的动机。

## 10. 环境

- 本机 Temp 目录被锁：pytest 必须 `--basetemp=.pytest-tmp`，否则全挂。
- 前台命令 300s 上限 + 思考模式单调用 150–400s：LLM 实验只能交回用户跑，我这边只能跑 fake 模型冒烟。定流程时先把"谁等得起"想清楚。
- **`/mnt/d` 上的 checkout 不能混用 WSL 与 Windows 的 uv**。在 WSL 里跑一次 `uv run`，Linux 版 uv 会把 `.venv` 重建成 Linux 布局（含 `lib64 -> lib` 符号链接），之后宿主 uv 报 `failed to remove file .venv\lib64: 拒绝访问 (os error 5)`。修法：`rm -rf .venv` 让宿主重建。规矩：**同一个 checkout 只能有一个 uv 宿主**；WSL 侧要跑 Python 就用裸 `python3`，别碰 `uv`。顺带：`.pytest_cache` 未被 gitignore，跑完测试记得清。


## 11. 实验记录里的配置描述与 toml 不符

现象：四份 dta19 实验记录都写着 `patch-1turn` 用了 "best_effort + 隐去 append/merge"，实际 `configs/toolsets/patch-1turn.toml` 里**两样都没有**——既没设 `apply_mode`（⇒ 默认 `atomic`），也没设 `hide_ops`。那段描述对应的是从未在这些 run 里用过的 `patch-1turn-lenient.toml`。
后果：`atomic` 下批次内任一 `replace` 的 `old` 匹配不上即**整批回滚**。每-op 失败率只有 0.24%~1.27%，却因连坐作废了 19.5%~83.7% 的已提交 op。l1 上 `patch` 的 cMER 被推高 46%（0.0112 → 0.0209），据此写出的"patch 在密集错误下改不动"的结论完全是假的。
教训：这比坑 #8（文档落后代码）更糟——**文档主动断言了一件假事，于是没人再去核 toml**。规矩：实验记录的 Arms 表必须与实际 toml 逐字段对拍，最好由脚本从 `report.json` 落盘的配置自动生成，而不是手写。

## 12. `--replay` 不重算报告

现象：改 `apply_mode` 后跑 `--replay`，打印 `changed=7`，但 `report.json` 的 `aggregate` 与 `per_sample` **逐字节没变**。
原因：`replay()` 只做两件事——更新磁带的 `session.output`，写 `report["replay"]` 段。**它从不重新评分**。重算在 `build_report`（从磁带 + scorer 重建），要单独跑 `--report-only`。
教训：`--replay` 后必须接 `--report-only`，否则读到的是陈数字。**而且陈得毫无异常迹象**——如果不是去核 `per_sample`，就会读出"best_effort 和 atomic 完全相同"，然后得出与真相相反的结论。和坑 #1 同形：成功地没干活，只有交叉核对能暴露。建议：`changed > 0` 时让 `--replay` 直接重建报告，或至少打一行"报告未重算"的警告。

## 13. `--replay` 会重 fold 全部臂，且毁掉失败会话

现象：只用 `--replay-with patch-1turn=...` 覆盖 patch，结果 `dta19-l2-doc-1t` 的 **rewrite 臂**聚合 cMER 从 0.0560 被抬到 0.4841。
原因：`replay()` 遍历 `report["toolsets"]` 里的**所有**臂重 fold，`--replay-with` 只决定用哪份配置。对 5 个 `failed:incomplete` 的 rewrite 会话，原始 run 的 `session.output` 按设计回退为原文（cMER ≈ noop）；replay 重 fold 时 `extract` 在空 tool_state 上返回**空串且不抛异常**，于是没走 `except: output = task.input` 的回退分支，cMER 变成 1.0000。
教训：**replay 只对"确定性后处理"安全，对"失败会话的回退语义"不安全**——回退发生在 loop 层（`status=failed` ⇒ 产出原文），而 replay 只重放 fold，丢掉了这层语义。规矩：replay 后必须逐样本对拍未被覆盖的臂；`failed:*` 的会话应在 replay 中原样保留 `session.output`，不参与重 fold。
（本次影响面：l0-chunk / l0-doc / l1-doc 三个 run 的非 patch 臂逐样本核对为零改动，只有 l2 的 rewrite 中招——因为只有它有"失败且无任何有效提交"的会话。）

# 概念：I/O 边界与无损保真

系统区分三层责任边界，杜绝隐式副作用介入核心流：

```text
sourceio       : bytes ↔ SourceText      负责编码、BOM、原始换行保真
partition      : SourceText ↔ segments   负责文本级物理无损切分
reconstruction : segments → SourceText   负责文本精确折叠还原
```

- **责任隔离**：文件级保真（`bytes ↔ str`）完全由 `sourceio` 承担。读取时必须禁用隐式换行转换。
- **文本级无损**：切分算法只保证 $\mathrm{reconstruct}(\mathrm{segments}) \equiv \mathrm{SourceText}$。
- **非破坏性**：空白折叠、Unicode 标准化、Markdown 格式化等改变文本内容的规整操作归 `transforms/`，默认严禁介入标准 ingest 流水线。

逐字符相等之外的等价关系，一律不叫 lossless。

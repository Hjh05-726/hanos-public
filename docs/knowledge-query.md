# 查询、原文定位与反向引用

`skills/hanos/scripts/knowledge_read.py` 是知识 CLI 的只读实现。每次调用重新从磁盘读取，没有持久查询索引，也不刷新笔记、索引或图谱。返回内容是选定范围内的证据；内容是否足以支持回答、来源是否矛盾，仍由 Agent 根据实际原文判断。

## 范围与路径

`Knowledge(config_path, scope_selector)` 要求绝对配置路径，从配置解析 `knowledge_home`，验证 JSON 登记表中**所有 active 条目**，再以 `id`、`name` 或仓库 `aliases` 选择一个范围。Latin 大小写不影响选择。重复 id、跨仓库 selector 冲突、缺失或越界目录均失败，不能跳过坏条目后继续。仓库别名仅用于选择范围，笔记别名单独检索。

登记目录作为查询范围；登记入口文件使用其 parent 作为范围，入口文件必须仍存在。第一版登记 id 必须是安全的单一路径段：`[A-Za-z0-9][A-Za-z0-9_.-]*`。这些约束不会重写旧登记表；不兼容输入明确失败。

所有 `read`/`safe` 路径相对于知识根，结果路径也相对于知识根。可以传入根内的绝对路径。普通路径拒绝 `..`、隐藏路径、符号链接和范围外路径；不存在的合法路径仅可由 `safe` 返回供受控写入规划，`read` 必须读取实际文件。扫描跳过隐藏目录、隐藏文件和符号链接，仅读取 `.md`/`.markdown` 文件。直接 `read` 可读取 UTF-8 Markdown 或文本。

`read(path, control=True)` 只定向读取 `.hanos/sources/<当前 scope_id>/...` 中的来源快照。它不能读取其他范围的来源、`.hanos/operations`、隐藏子目录或符号链接；来源快照也不进入普通查询。根目录、范围及访问路径在每次访问时复核。JSON 内容和资料正文都是数据，不产生配置修改或扩大范围的授权。

## 返回的证据

`read(path, section=None, control=False)` 返回 `path`、`title`、`section`、`sha256`、`excerpt`、`start_line`、`end_line`、`warnings`、`properties`。摘要计算对象是该次读取的原始字节；行号是一基、两端包含，片段保留原换行符。空文件使用 `start_line=1, end_line=0` 表示空区间。UTF-8 BOM 不作为正文展示，但参与摘要。

章节支持 Markdown ATX 标题（`#` 至 `######`），按完整标题匹配，不区分 Latin 大小写。片段从章节标题开始，到下一个同级或更高级标题之前结束。重复章节标题返回 `ambiguous_section`；不存在返回 `section_not_found`。代码块和代码中的伪标题不参与章节定位。Setext 标题和自动生成的重复标题锚点不属于第一版章节定位合同。

行号绑定返回的 `sha256`。文件改变后必须重新调用，不得把旧行号当作新版本位置。

## 查询顺序与基础属性

`query(term, filters=None, section=None)`：

1. 在当前范围内按基础属性进一步筛选。
2. 优先完整匹配笔记标题、文件名（含或不含扩展名）、知识根相对路径、笔记 `aliases`。
3. 没有名称命中时，以不区分 Latin 大小写的正文子串匹配补充候选。

查询返回 `scope`、`query`、`filters`、`status`、`hits` 和 `warnings`。唯一名称命中为 `ok`，同名或重叠别名为 `ambiguous`，仅关键词命中为 `candidates`，当前范围没有命中为 `not_found`。候选并不代表事实已确认；没有结果也不说明其他范围或外部世界没有相关内容。完整原文可用于上下文复核；第一版不截断长文。

Frontmatter 支持文件开头 `---` 包围的基础字段：ASCII 标识符 key、单行纯字符串、简单单/双引号字符串、`[one, two]` 列表、缩进 `- item` 字符串列表。不进行数字、布尔、日期类型转换；筛选值是字符串，大小写敏感，列表按成员精确匹配。任何可解析的自定义标量/列表字段都可以筛选。

嵌套对象、跨行标量、YAML anchors/tags、复杂转义等不支持；对应字段不参与筛选，并在 `warnings` 明确报告。重复字段不取任意一个值。未知字段和不支持的结构一直留在原文件里，读取从不重写 frontmatter。解析覆盖不等于语义理解覆盖。

## 真实引用与问题链接

`backlinks(target)` 以目标笔记名称、路径或别名查找当前范围内的实际引用。返回 `scope`、`status`、`target_candidates`、`hits`、`link_issues` 和 `warnings`。每条引用包含引用者路径、读取摘要、真实行号、起始列、整行原文、所在章节、目标章节和候选目标。

支持：

- `[[Note]]`、`[[Note#Heading|Label]]`；简单名称同时匹配标题/文件名/笔记别名。
- `[[project/path/Note]]` 的知识根相对路径或引用者相对路径；两个解释均存在时报告歧义。
- `[label](relative.md)`、`[label](../relative.markdown#heading)`、`[label](<relative path.md>)`，以及可选双引号 title。
- Markdown 相对链接允许父目录段，但规范化后的目标必须仍在选定范围。WikiLink 路径不得通过目录跳出范围。
- 章节可使用完整标题或简单小写连字符 slug；重复匹配、失效章节分别报告。

`hits` 仅放唯一解析成功的链接。`link_issues` 保留当前扫描范围内的 `broken`、`ambiguous`、`unsafe`、`broken_section`、`ambiguous_section` 问题，方便显式报告；问题不自动修复。目标笔记本身歧义时，顶层 `status=ambiguous`，不得把合并候选当作唯一目标。

围栏代码块（反引号或波浪号）、四空格/Tab 缩进代码、同一行的单/多反引号 inline code、HTML 注释、图片/嵌入及外部 URL 不计为真实引用。第一版不解析引用式 Markdown 链接、跨行 inline code、括号嵌套的链接目标、脚注或 HTML 链接；这些格式不声明完整覆盖。纯同词与语义近似不产生链接。

## 程序接口示例

```python
knowledge = Knowledge(Path("/isolated/config.json"), "example-project")
result = knowledge.query("名称", {"status": "current"})
quote = knowledge.read("projects/example-project/note.md", section="证据")
source = knowledge.read(".hanos/sources/example-project/version/source.md", control=True)
links = knowledge.backlinks("名称")
```

异常为 `KnowledgeError(status, message)`，调用者应展示实际状态与原因，不得以静默裸读取或写入绕过边界。该模块不提供对不参与工具锁的外部编辑器的事务快照保证；每一条返回证据只绑定自身读取时的字节版本。

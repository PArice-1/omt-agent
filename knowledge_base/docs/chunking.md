# 文件切分

[返回项目首页](../README.md) · [架构总览](architecture.md)

```python
from dataclasses import asdict

from rag_mcp.chunk import Chunker

chunker = Chunker(chunk_size=2048)
chunks = chunker.chunk("./knowledge-base/guide.md", ".md")
notes = chunker.chunk("./knowledge-base/notes.txt", "txt")
# 后缀可省略，从文件名推断；支持大写扩展名。
notes = chunker.chunk("./knowledge-base/notes.txt")
# 文件列表逐个推断后缀，可混合 MD/TXT，按输入顺序合并为 list[Chunk]。
chunks = chunker.chunk(["./knowledge-base/guide.md", "./knowledge-base/notes.txt"])

for chunk in chunks:
    print(chunk.text)
    print(chunk.metadata.heading_path)
    print(asdict(chunk))
```

单文件和文件列表都返回一个合并后的 `list[Chunk]`，空列表返回 `[]`。列表参数支持 `list[Path]`、`list[str]` 和混合的 `list[str | Path]`，使用泛型声明以兼容静态类型检查。传入显式 `suffix` 时对列表中的所有文件生效；省略时按各文件扩展名分别选择解析函数。每个片段只有 `text` 和 `metadata` 两个字段。`asdict()` 后的结构：

```python
{
    "text": "正文。\n",
    "metadata": {
        "source": "/absolute/path/guide.md",
        "heading_path": ["指南", "安装"],
        "start_line": 2,
        "end_line": 3,
        "start_index": 11,
        "end_index": 15,
    },
}
```

MD/TXT 的 `source` 是展开 `~`、解析相对路径和符号链接后的绝对路径；Parquet 的 `source` 是该行原始资料 ID 的字符串形式。`heading_path` 从父标题排列到子标题；前言、无标题文档、TXT 和 Parquet 正文使用 `[]`。

行号和字符偏移都从 **0** 开始，结束位置不包含在范围内。行范围覆盖片段涉及的所有行；多个片段可能位于同一行，应使用 `原文[start_index:end_index]` 精确还原正文。字符偏移按 Python 字符计算，不是 UTF-8 字节偏移。原文的 CRLF、CR 和 LF 换行会保留。

### 目录与规则

```text
src/rag_mcp/chunk/
├── __init__.py  # 公开入口
├── chunker.py   # Chunker 类，按后缀调度
├── rules.py     # Markdown、TXT 各自的 RecursiveRules
├── schema.py    # Chunk、ChunkMetadata
├── markdown.py # Markdown 标题解析与递归切分
├── text.py     # TXT 递归切分，共用纯文本 chunker
├── parquet.py  # 可配置列名，分批读取、逐篇切分，按需导入 pyarrow
├── _shared.py  # 原文读取、偏移和行号映射
└── files.py    # 文件发现、排序与去重
```

切分使用 Chonkie `RecursiveChunker`，采用 `character` tokenizer，默认每片最多 **2048 个字符**。这是固定规则切分，不调用模型，也不生成语义向量。规则集中维护在 `rules.py`：

- Markdown：先用 Markdown 语法识别顶层 h1–h6 和 Setext 标题；再在每个章节内依次尝试段落、换行、中英文句末标点、从句标点、空格，最后按字符数切分。
- TXT / Parquet 正文：不解释 Markdown 语法，依次尝试段落、换行、中英文句末标点、空格，最后按字符数切分。

只有超过大小限制的部分才进入下一层规则。Markdown 标题保存在元数据中，正文不重复附加标题；代码块、列表和引用内部的标题不建立章节。超长代码块也会继续切分。空白章节和空白片段不生成结果，空文件返回 `[]`。不支持的后缀抛出 `ValueError`，文件读取及解码错误直接向上传递。

## Parquet 资料

小文件可使用 `Chunker(chunk_size=1024).chunk("documents.parquet")`，默认读取 `id` 和 `text` 列。大文件使用流式入口，避免构建整个文件的片段列表：

```python
from rag_mcp.chunk import iter_parquet_chunks

for chunk in iter_parquet_chunks(
    "documents.parquet",
    id_column="id",
    text_column="text",
    chunk_size=1024,
    batch_size=1000,
    max_documents=100,
):
    print(chunk.metadata.source, chunk.metadata.start_index, chunk.metadata.end_index)
```

`max_documents` 限制原始资料行数，不限制每篇的片段数。所有片段的来源和定位均相对于该行正文，保留原文，忽略空白片段；空白正文、无效 ID、所选范围的重复 ID 和缺失列会报错。不同 ID 的相同正文不会被内容去重。读取器按批缓存行、逐篇缓存片段，并保留已见 ID 集合，所以不是完全常量内存。

需要可选依赖 `pyarrow`，本项目可执行 `uv sync --group eval`。普通 MD/TXT 导入和使用不要求安装它。Parquet 入口不认识 T2Retrieval、queries 或 qrels；调用方负责只选择适合作为资料的文件。

本次仅扩展显式 `Chunker` 和流式 Parquet 入口；`search_files()`、`build_kb()`、MCP 启动构建仍只发现和处理 MD/TXT，不把“一文件多资料”的语义硬塞入现有按文件增量去重流程。

原 `chunk.py` 已拆成此包。`markdown_parser()`、`parse_md_list()` 和 `search_md_files()` 入口继续保留；原 `ChunkInfo` 的扁平字段改为 `Chunk.text` 与 `Chunk.metadata`，标题路径从 tuple 改为 list。`search_files()` 可同时发现 MD 和 TXT。

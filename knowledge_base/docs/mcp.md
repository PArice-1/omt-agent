# MCP 与检索

[返回项目首页](../README.md) · [架构总览](architecture.md)

## 直接使用 Python

```python
from rag_mcp.mcp import KnowledgeBase

kb = KnowledgeBase(db_path="./.qdrant", collection_name="knowledge")
print(kb.stats())
print(kb.search("如何创建虚拟环境？", limit=5, min_score=0.3))
print(kb.keyword_search("ERROR42", limit=20))
print(kb.list_documents(limit=50))
```

`KnowledgeBase` 每次操作按需打开并关闭数据库，同一实例通过锁串行访问；不存在的数据库按空库返回，不创建存储目录。不扫描或读取原始文档，因此源文件移动或删除后仍可检索已入库内容。语义搜索仅为问题调用一次 Ollama，空库或没有匹配来源时不调用模型。

## 启动服务

```bash
uv run rag-mcp --db-path ./.qdrant --collection knowledge
# 等价模块入口：
uv run python -m rag_mcp.mcp.server --db-path ./.qdrant --collection knowledge
```

使用 stdio 传输，stdout 仅用于 MCP 协议。默认存储目录和集合与 `build_kb` 一致；自定义时需在构建端和服务端传入相同参数。服务工厂 `create_server(db_path, collection_name)` 只注册工具，导入模块不会扫描文件、打开数据库或请求模型。

### 启动时增量构建

添加 `--build-on-start`，在 `main()` 中先调用 `build_kb()`，成功并释放数据库锁后才启动 stdio 服务：

```bash
uv run rag-mcp --build-on-start \
  --source ./knowledge-base ./other-docs ./notes/selected.md \
  --db-path ./.qdrant --collection knowledge --chunk-size 2048
```

- 不传 `--build-on-start` 时保持只读启动，不检查源文件；`--source` 必须与该开关一起使用。
- 开启构建但不传 `--source` 时，默认读取当前工作目录下的 `./knowledge-base`，该目录必须存在。`--source` 支持一个或多个目录/MD/TXT 文件；相对路径按进程工作目录解析。
- `--chunk-size` 默认 2048，仅用于启动构建；数据库路径和集合与后续工具调用一致。
- 复用已有文件去重：完整入库且内容、处理配置未变化的文件跳过切分和向量化，新增或修改文件才处理。修改文件追加新版本，不会清理旧版本或已删除文件的记录。
- MCP 启动构建时丢弃普通进度输出，不污染 MCP stdout，也不再将进度转发到 stderr；独立 `rag-build-kb` 命令仍显示进度。异常不会被吞掉：路径无效、模型请求失败或数据库错误会使进程退出，不继续提供可能过期的检索服务。
- 构建只在进程启动时执行一次，不监听文件变化，也不在每次搜索前重建。首次导入较多资料可能延迟 MCP 握手，需相应调大客户端启动超时，或先用 `rag-build-kb` 完成首次构建。
- 不要让其他服务或构建进程同时操作同一个本地数据库；工具仍全部只读，构建路径由启动配置指定而不是由 AI 工具参数指定。

MCP 客户端配置示例（把绝对路径替换为实际路径）：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/rag-mcp",
        "run", "rag-mcp",
        "--build-on-start",
        "--source", "/absolute/path/to/rag-mcp/knowledge-base",
        "--db-path", "/absolute/path/to/rag-mcp/.qdrant",
        "--collection", "knowledge"
      ]
    }
  }
}
```

## 可用工具

所有工具只读，以 JSON 文本返回数据，不暴露向量，不提供删除、任意文件读取或由模型指定目录入库的工具。

| 工具 | 参数与用途 |
|---|---|
| `search_knowledge` | `text`、`limit=5`、`source=None`、`min_score=None`；Cosine 语义搜索，得分降序，最低分包含端点 |
| `search_keyword` | `text`、`limit=20`、`offset=0`、`source=None`；标题/正文大小写不敏感的子串匹配，适合函数名和错误码，不按相关度排序 |
| `list_documents` | `limit=50`、`offset=0`；列出来源、处理标识、写入批次、已存片段数和完整性 |
| `get_document` | `source`、`processing_key=None`、`ingestion_id=None`、`limit=20`、`offset=0`；读取已入库片段，不读取磁盘原文件 |
| `get_chunk` | `chunk_id`；根据检索返回的 `id` 精确读取一个片段，不存在返回 `null` |
| `get_knowledge_base_stats` | 无参数；集合是否存在、模型、维度、片段数、来源数及文档条目完整性 |

工具中的 `limit` 为 1–100；`offset` 是非负的**结果跳过条数**，不是 Qdrant 内部的 Point ID 游标。分页结果包含 `items`、`offset`、`limit`、`has_more`；文档列表和文档读取另有 `total`。关键词搜索不返回 `total`，找到足够匹配后即可停止，不会为统计总数额外扫描剩余记录。

搜索和片段读取结果包含 `id`、`text`、`source`、`heading_path`、原文定位及处理标识等字段；语义搜索另有 `score`。原始行号和字符偏移均从 0 开始、结束位置不包含。后续可用结果中的 `source` 读取文档，用 `id` 读取具体片段。

文档条目按 `(source, processing_key, ingestion_id)` 分组，同一来源的历史版本和不同写入尝试分别列出。`complete=true` 表示该次写入的片段编号完整，`false` 表示不完整，缺少完成度元数据的旧记录为 `null`。统计中的 `source_count` 是不同来源数，`document_count` 是这些分组的数量，并非唯一文件内容数。`get_document` 不指定版本和批次时返回该来源的所有记录，不自动推断“最新版”；返回的是有序 chunks，而非无损重建的原始文件。

目前语义搜索也可能返回历史版本和未完成写入留下的片段；需要指定版本时，可从文档列表取得处理标识和写入批次后调用 `get_document`。文档列表/统计需要扫描集合状态元数据，关键词搜索需要扫描候选正文，文档读取需收集所选来源的片段后排序，暂未实现独立文档索引或全文索引。读工具并不意味着全流程使用常量内存。

客户端的工作目录决定相对路径的解析位置；建议配置绝对路径。服务使用 stdio，不监听 HTTP 端口，也没有终端聊天界面，通常由 Agent 客户端启动和管理进程。

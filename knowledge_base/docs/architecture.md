# 架构总览

[返回项目首页](../README.md)

## 项目定位

rag-mcp 将本地 MD/TXT 资料写入 Qdrant，再通过 MCP 暴露只读检索工具。它提供 RAG 的资料处理和检索能力，不包含聊天界面或最终答案生成；答案由接入的 Agent 根据工具返回的资料组织。

## 两条处理流程

### 构建：资料写入数据库

```text
源目录 / MD、TXT 文件
    → 文件发现与路径合并
    → Fliter：按文件内容和处理配置去重
    → Chunker：按章节和字符数切分
    → Embeder：调用 Ollama 生成文档向量
    → VectorDatabase：写入 Qdrant
    → 关闭后重新打开，验证持久化
```

独立入口是 `rag-build-kb`。MCP 启动时指定 `--build-on-start` 也会复用相同的 `build_kb()`，完成后才启动协议服务。详见[构建与去重](ingestion.md)。

### 检索：Agent 通过 MCP 读取数据库

```text
Agent / MCP 客户端
    → stdio 协议
    → MCPServer：分发工具调用
    → mcp/tools：工具参数与 JSON 输出
    → KnowledgeBase：检索、文档读取、统计
    → VectorDatabase / QdrantClient：访问持久化记录
    → 返回资料片段
    → Agent 组织答案
```

语义搜索只为当前问题生成一次向量，再查询已存文档向量；其他工具不请求模型。关键词搜索在读取的标题和正文中做子串匹配，并非向量搜索或独立全文索引。详见[MCP 与检索](mcp.md)。

## 独立评估流程

```text
T2Retrieval corpus → 通用 Parquet 流式读取与 TXT 规则切分
                  → Embeder → 独立 Qdrant 集合
queries + qrels   → 完整资料覆盖筛选 → KnowledgeBase 搜索
                  → 原始文档 ID 去重 → 指标均值 → JSON/Markdown 报告
```

`evals/build_index.py` 与 `evals/run.py` 分别负责评估入库和批量检索，不把数据集标注规则放入 `src`。查询不按标准答案 ID 过滤，资料向量不会在每次查询时重新构建。仓库保留 `evals/results/` 的真实报告和 `evals/data/storage/` 的本地数据库展示快照，原始 Parquet 不提交。详见[检索评估](evaluation.md)。

## 模块职责

| 模块 | 职责 |
|---|---|
| `build_kb.py` | 串联构建流程、处理输入路径、验证持久化 |
| `config.py` | 构建和服务共用的默认存储路径与集合 |
| `chunk/` | MD/TXT 文件发现与切分、通用 Parquet 分批读取与长文切分 |
| `fliter/` | 计算处理标识，过滤已完整入库或本批重复文件 |
| `embed/` | 组织片段向量化输入，调用并校验 Ollama 响应 |
| `vector_databbase/` | 本地 Qdrant 生命周期、集合管理和向量写入 |
| `mcp/knowledge_base.py` | 查询过滤、语义/关键词搜索、文档读取和统计 |
| `mcp/server.py` | 服务创建、启动参数、可选启动构建和 stdio 运行 |
| `mcp/tools/` | 将知识库方法注册为六个只读 MCP 工具 |

Parquet 入口 `iter_parquet_chunks()` 支持配置 ID/正文列名，复用 TXT 的递归规则和原文定位逻辑。`pyarrow` 按需导入，安装 `eval` 依赖组即可使用，不增加 MD/TXT 和 MCP 的必需依赖。常规 `build_kb()` 与文件发现仍只处理 MD/TXT，避免把 Parquet 的“一文件多资料”语义混入按文件增量去重流程。详见[文件切分](chunking.md)。

当前目录名 `fliter`、`vector_databbase` 与代码导入保持一致。

`KnowledgeBase` 使用 `VectorDatabase`，但也直接通过 `db.client` 调用 Qdrant 的查询方法，数据库细节目前并未完全封装在存储模块内部。

## 项目结构

```text
src/rag_mcp/
├── build_kb.py          # 多目录/文件构建入口和 CLI
├── config.py            # 构建与服务共用的默认存储配置
├── chunk/               # MD/TXT 与 Parquet 正文切分
├── fliter/              # 切分前文件去重
├── embed/               # Ollama 向量化
├── vector_databbase/    # Qdrant 持久化封装
└── mcp/
    ├── __init__.py       # 公开 KnowledgeBase
    ├── knowledge_base.py # 持久化检索、文档读取和统计
    ├── server.py         # MCP 服务工厂及 stdio 入口
    └── tools/
        ├── search.py     # 语义搜索、关键词搜索
        ├── documents.py  # 文档列表、文档和片段读取
        ├── knowledge.py  # 知识库统计
        └── _shared.py    # JSON 输出和只读工具声明
```

## 数据与生命周期

- Qdrant Point 的向量字段保存 embedding，payload 保存正文、来源、标题和定位等元数据；入库时还可附带处理版本及完成度信息。详见[向量存储](storage.md)。
- 默认数据库是当前工作目录下的 `./knowledge-base/storage`，默认集合是 `knowledge`；不需要额外启动 Qdrant 服务。
- 服务创建和模块导入不扫描资料、不打开数据库；启动构建只由 `main()` 根据参数执行。
- 每次知识库读取按需打开并关闭数据库，同一个实例通过锁串行访问。同一数据库不能被多个本地客户端进程同时操作。
- MCP stdout 专用于协议；启动构建的普通进度输出会丢弃，异常仍向外抛出。独立构建命令保留进度输出。
- 数据库保存的是入库快照；启动构建不持续监听资料变化。文件修改追加新版本，源文件删除不会删除历史记录，搜索也不自动限定最新版。

## 历史迁移

MCP 相关实现统一位于 `mcp/`：服务入口是 `mcp/server.py`，工具位于 `mcp/tools/`，持久化读取逻辑位于 `mcp/knowledge_base.py`。原 `rag/` 和顶层 `tools/` 已迁移，Python 导入改为 `rag_mcp.mcp` 和 `rag_mcp.mcp.tools`，模块启动命令改为 `python -m rag_mcp.mcp.server`；CLI 命令 `rag-mcp` 保持不变。旧 `query.py`、`embeding_files.py` 内存构建/检索链路及 `embeding.py` 兼容入口已删除；对应测试由持久化检索、MCP 和 Ollama 测试替代。旧模块导入路径不再保留兼容层，搜索结果正文统一使用 `text` 字段而非旧 `content`。原始资料和已有数据库不删除。

## 验证

```bash
uv run python -m unittest discover -s tests -v
```

测试使用临时真实 Qdrant 数据库和 mock 模型请求，不要求运行 Ollama；包括构建去重、持久化检索、启动构建和真实 stdio 子进程握手测试。

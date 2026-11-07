# rag-mcp

本地持久化 RAG 知识库：将 Markdown/TXT 资料写入 Qdrant，通过 MCP 为 Agent 提供语义搜索、关键词搜索和文档读取。

- 支持 UTF-8 编码的 `.md`、`.txt`，可导入多个目录或文件。
- 通用切分入口额外支持 Parquet 分批读取与长文切分，保留原始资料 ID；常规 MCP 建库仍只发现 MD/TXT。
- 使用 Ollama 生成向量，Qdrant 本地存储，无需单独部署数据库服务。
- 支持启动前增量构建，未变化且完整入库的文件跳过切分和向量化。
- 提供六个只读 MCP 工具；最终答案由接入的 Agent 生成，本项目不包含聊天界面。

## 快速开始

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 [Ollama](https://ollama.com/)。以下命令在项目根目录执行。

### 1. 安装依赖并准备模型

```bash
uv sync --frozen
ollama pull qwen3-embedding:0.6b
```

确保 Ollama 服务已运行；如果尚未启动，先在另一个终端执行 `ollama serve`。默认向量接口为 `http://localhost:11434/api/embed`。

### 2. 准备资料并启动

```bash
mkdir -p knowledge-base
# 将需要导入的 MD/TXT 资料放入 knowledge-base 后执行：
uv run rag-mcp --build-on-start
```

默认扫描 `./knowledge-base`，数据库保存到 `./knowledge-base/storage`，集合为 `knowledge`。构建完成后通过 stdio 等待 MCP 客户端连接，不会出现交互式问答提示。

也可以先单独构建，再启动只读服务：

```bash
uv run rag-build-kb ./knowledge-base
uv run rag-mcp
```

自定义多个资料路径和存储位置：

```bash
uv run rag-mcp --build-on-start --source /path/to/docs /path/to/notes.md \
  --db-path /path/to/storage --collection knowledge
```

示例路径需替换为实际路径。更多构建参数见[构建与去重](docs/ingestion.md)，启动参数见 [MCP 与检索](docs/mcp.md)。

## 接入 Agent

在支持 `mcpServers` 配置格式的客户端中添加以下配置，将 `/absolute/path/to/rag-mcp` 替换为项目的实际绝对路径：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/rag-mcp",
        "run", "rag-mcp", "--build-on-start"
      ]
    }
  }
}
```

由客户端启动服务即可，无需再手动启动一份。连接后可以让 Agent：

> 先搜索我的知识库，说明项目如何安装，并注明资料来源。

可用工具：`search_knowledge`、`search_keyword`、`list_documents`、`get_document`、`get_chunk`、`get_knowledge_base_stats`。参数和返回结构见 [MCP 与检索](docs/mcp.md)。

## 使用注意

- 启动构建只检查一次，不监听运行期间的文件变化；不加 `--build-on-start` 则不检查源文件。
- 修改文件会追加新版本，不会自动删除旧版本或已删除文件的记录，搜索也不自动限定最新版。
- 语义搜索只向量化当前问题；其余工具不调用 Ollama。启动构建的普通进度输出静默，异常仍正常抛出。
- 不要让多个 MCP 服务或构建进程同时操作同一个本地数据库。首次构建较慢时，先单独构建或调大客户端启动超时。

## 检索评估与示例报告

使用 T2Retrieval 评估检索流程：Parquet 正文先复用 `src` 的 TXT 规则切分，再向量化入库；问题单独检索，片段按原始资料 ID 去重后，计算 Hit@K、Recall@K 和 MRR@K。

**无需启动模型即可查看已保存的真实运行结果：**

- [评估报告（Markdown）](evals/results/report-20261107T082120064449Z.md)：平均指标和单题指标。
- [完整结果（JSON）](evals/results/report-20261107T082120064449Z.json)：配置、标准资料、片段/文档排名和单题评分。
- [结果范围与解释](evals/results/README.md) · [Qdrant 数据库快照](evals/data/storage/README.md)。

| 已保存示例 | 数值 |
|---|---:|
| 候选原始资料 / 切分片段 | 1000 / 1528 |
| 实际评估问题 | 203 |
| 文档 K / 片段检索预算 | 5 / 50 |
| 平均 Hit@5 | 0.990148 |
| 平均 Recall@5 | 0.837536 |
| MRR@5 | 0.990148 |

这是缩小候选库、仅选择相关资料全部在库的问题得到的**本地文档级检索结果**，不是完整 T2Retrieval 官方基准，也不代表生成答案的正确率或片段证据完整性。

复现时安装评估依赖，按[评估说明](evals/README.md#准备数据)下载原始 Parquet，并确保 Ollama 可用：

```bash
uv sync --frozen --group eval
```

一键执行新实验：先将 corpus 前 100 篇切分入库，再评估最多 10 道符合条件的问题，生成 JSON 和 Markdown 报告：

```bash
./scripts/eval.sh --max-documents 100 --chunk-size 1024 --max-queries 10 --k 5 --fetch-k 50
```

默认自动生成新集合名，不复用、覆盖或删除旧集合；入库失败就停止，不进入评估。可用 `./scripts/eval.sh --help` 查看路径、批大小和输出参数。**每次运行都会生成新的资料向量**，不是只查询已有数据库。

如果只想使用已保存的 `kb_eval_1` 集合评分，不重复入库：

```bash
uv run --group eval python -m evals.run --collection kb_eval_1 --max-queries 10 --k 5 --fetch-k 50
```

`evals/results/` 与 `evals/data/storage/` 随仓库保留，方便展示；原始 Parquet 下载文件不提交。数据库中也保留历史未完成集合，评估入口会拒绝使用它们。运行期间不要同时访问或修改同一个本地数据库。

## 文档

| 文档 | 内容 |
|---|---|
| [架构总览](docs/architecture.md) | 构建与检索流程、模块职责、目录结构和迁移说明 |
| [构建与去重](docs/ingestion.md) | CLI/Python 构建、处理标识、完整性判断和重试限制 |
| [文件切分](docs/chunking.md) | Markdown/TXT/Parquet 读取、切分规则、原始 ID 和精确定位 |
| [片段向量化](docs/embeddings.md) | Ollama 配置、输入组织和向量结果结构 |
| [向量存储](docs/storage.md) | Qdrant 集合、写入、持久化和客户端生命周期 |
| [MCP 与检索](docs/mcp.md) | 启动配置、六个工具、Python 检索与分页语义 |
| [检索评估](docs/evaluation.md) | T2Retrieval 入库、文档级检索评分、指标口径和结果报告 |

## 测试

```bash
uv run --group eval python -m unittest discover -s tests -v
uv run --group eval python -m unittest discover -s evals/tests -v
```

测试使用临时数据库并 mock 模型请求，无需运行 Ollama，也不会修改仓库中保留的评估快照。

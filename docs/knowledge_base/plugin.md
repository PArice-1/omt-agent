# 知识库插件接入

knowledge_base 独立提供资料处理和检索；backend 默认不安装、不启用它。Python 包继续叫 rag_mcp，命令继续叫 rag-mcp / rag-build-kb。

## 安装与构建

以下命令从仓库根目录执行。安装插件依赖并准备 Ollama 的 embedding 模型：

```bash
uv sync --frozen --project knowledge_base
ollama pull qwen3-embedding:0.6b
```

确保 Ollama 已运行。按需将 MD/TXT 资料放在 ~/.omt/knowledge-database，再显式构建：

```bash
uv run --frozen --project knowledge_base rag-build-kb "$HOME/.omt/knowledge-database" \
  --db-path "$HOME/.omt/knowledge-database/storage" --collection knowledge
```

构建会写数据库并请求本机向量模型。它不是安装或默认启动步骤，已有配置、资料和存储不会被迁移脚本改写。更多参数见 [构建说明](ingestion.md)。

## 接入 CLI 或 Web 后端

配置脚本输出符合 backend 启动字段的 JSON，不读写资料，不请求模型。已构建知识库接入 CLI：

```bash
export OMT_CLI_MCP_SERVERS="$(python3 scripts/knowledge-base-config.py)"
./scripts/start-cli.sh
```

只启用 Web 后端时，在同一终端设置 API 的独立配置：

```bash
export OMT_API_MCP_SERVERS="$(python3 scripts/knowledge-base-config.py)"
./scripts/start-web.sh
```

只读配置使用默认 ~/.omt/knowledge-database/storage；可用 --db-path、--collection 替换。显式指定 --build-on-start 时才把 --source 传给插件，启动会先检查并增量构建资料。配置中的 --source 在未开启构建时仅用于推导默认存储位置。

```bash
python3 scripts/knowledge-base-config.py --source /absolute/path/to/docs \
  --db-path /absolute/path/to/storage --build-on-start
```

关闭时将对应变量设为 `{}` 或取消设置。两个入口不互相继承 MCP 配置，安装插件不会使其他入口自动连接。显式配置错误或插件不可用仍正常报告失败，不假装检索成功。

## 独立使用与进程约束

`scripts/start-knowledge-base.sh` 保持 stdout 为 MCP 协议数据，适合放在客户端的 command 中，由客户端管理进程生命周期；手动运行会等待 stdio 请求，不是聊天界面。其他支持 mcpServers 的客户端可把配置脚本输出放入其 mcpServers 字段。

同一 Qdrant 本地目录只能由一个进程持有；CLI 和 API 各自启动插件时，应选择使用其中一个入口，或分别指定 --db-path 并构建独立索引。例如 CLI 使用 storage-cli，API 使用 storage-api。仅修改 collection 不能避免目录锁冲突，资料构建进程也不能与检索进程同时打开同一目录。

本次保留 stdio；未来共享单个常驻知识库进程时再增加 Streamable HTTP。backend 已能配置 streamable_http 客户端，不表示当前知识库入口已支持该传输。

搜索和读取工具只负责返回资料及来源，最终回答由 Agent 组织。必须检索的业务流程应由 backend 明确保证检索发生；仅注册 MCP 工具不保证每次问答都调用它。工具列表见 [MCP 与检索](mcp.md)。

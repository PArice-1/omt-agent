# OMT Monorepo

OMT 的终端、Web 与可选知识库插件统一在一个 Git 仓库中开发。Python 包名与命令继续沿用 `omt`、`omt-api` 和 `rag-mcp`。

| 目录 | 职责 |
| --- | --- |
| [backend](backend/README.md) | CLI/TUI、HTTP API、Agent 与会话核心 |
| [knowledge_base](knowledge_base/README.md) | 可独立安装、通过 MCP 接入的知识库 |
| [frontend](frontend/README.md) | Next.js 本机 Web 界面 |
| [scripts](scripts/) | 安装、启动和插件配置入口 |
| [docs](docs/README.md) | 统一文档、接口契约与测试说明 |

## 快速开始

需要 Python 3.12+、uv、Node.js 22.19+、npm 和 Bash，支持 Linux/macOS。

```bash
./scripts/setup.sh
./scripts/start-cli.sh          # 默认 TUI
./scripts/start-cli.sh --plain  # 逐行模式
./scripts/start-web.sh          # API :8000 + Web :3000
```

CLI 与 Web 是两种使用入口，可按需选择。Web 默认打开 http://127.0.0.1:3000；尚未配置模型也能进入配置页面。启动不会自动调用聊天模型，首次使用在 TUI 的 F2 / `/login` 或 Web 的“添加模型”完成配置。

CLI 与 API 保留调用者的工作目录；会话按工作目录归属，文件/Bash 工具也基于该目录。模型配置及会话数据继续使用 `~/.omt`。

换端口或单独启动 API：

```bash
./scripts/start-web.sh --api-port 8001 --port 3001
./scripts/start-api.sh --port 8001
```

Web 脚本管理本次创建的两个进程组，Ctrl+C 一起退出；已有端口被占用时停止并提示，不接管已有服务。完整启动、生产模式及失败处理见 [快速开始](docs/quickstart.md)。

## 可选知识库

默认不安装、不启用知识库，backend 可独立运行。插件需要时再安装与配置：

```bash
./scripts/setup.sh --with-knowledge-base
export OMT_CLI_MCP_SERVERS="$(python3 scripts/knowledge-base-config.py)"
./scripts/start-cli.sh
```

上述配置只连接已有知识库；首次构建、Ollama 要求、API 接入及不同进程的数据库目录约束见 [插件接入](docs/knowledge_base/plugin.md)。

当前应用面向可信本机、单用户；内置工具能够读写文件和执行命令。CLI/API 不要同时运行同一个会话，前后端默认仅监听回环地址。

开发与检查见 [开发说明](docs/development.md)，历史保留和原项目目录说明见 [迁移记录](docs/migration.md)。

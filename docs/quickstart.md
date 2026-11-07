# 快速开始

以下命令从仓库根目录执行。需要 Python 3.12+、uv、Node.js 22.19+、npm 和 Bash；不自动安装系统软件。

## 安装和启动

```bash
./scripts/setup.sh
./scripts/start-cli.sh
```

默认使用全屏 TUI，`--plain` 切换逐行模式。无模型配置时按 F2 或输入 `/login`；普通启动只检查本地配置，显式登录会查询厂商模型目录，提交普通消息才会调用聊天模型并可能执行工具。

使用 Web 时运行：

```bash
./scripts/start-web.sh
```

打开 http://127.0.0.1:3000。API 默认在 http://127.0.0.1:8000；缺少模型配置时可在页面添加模型，健康检查只代表 API 存活。Ctrl+C 会关闭本次启动的 API、Web 及其子进程。

```bash
./scripts/start-web.sh --api-port 8001 --port 3001 --timeout 60
./scripts/start-api.sh --port 8001
```

也可使用环境变量 OMT_API_PORT / OMT_WEB_PORT。Web 脚本优先使用命令行参数，并让 Next.js 连接本次启动的 API；它不会复用已运行的 API。后端或前端端口占用、依赖缺失、API 超时或任一进程退出时会明确失败，并清理本次创建的进程。

CLI/API 的 cwd 保持为调用命令时所在目录。要操作其他项目，先切换目录，再使用脚本绝对路径；不要用 cd 到 backend 作为安装定位方式。已有会话仍只在原工作目录下列出。

## 本机生产模式

两个终端分别运行，端口及 OMT_BACKEND_URL 保持一致：

```bash
./scripts/start-api.sh
```

```bash
npm --prefix frontend run build
npm --prefix frontend start
```

独立启动 Next.js 可在 frontend/.env.local 中设置服务端 OMT_BACKEND_URL；`start-web.sh` 则为它创建的前端进程直接注入对应 API 地址。

## 知识库与故障定位

知识库是可选插件，安装和构建见 [插件接入](knowledge_base/plugin.md)。setup 默认只安装 backend/frontend，不下载 Ollama 模型或导入资料。真实用户配置留在 `~/.omt`；需要 Python/Node 依赖更新时重新运行 setup。

启动失败先查看本机端口、依赖安装状态及终端中的 API 日志。API 未就绪和 API 进程不存在是两种状态；`/health` 成功也不保证模型可调用。详细配置见 [开发说明](development.md)。

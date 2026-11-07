# 后端协作补充

通用约定见 [根协作规范](../AGENTS.md)。后端包含 CLI/TUI、HTTP API 和共用 Agent 核心。

- 修改 Session、历史、模型连接、流或工具前阅读 [架构说明](../docs/omt/architecture.md)；定位入口见 [文档导航](../docs/omt/README.md)。
- 修改测试前阅读 [测试规范](../docs/omt/tests/README.md) 和对应模块说明，行为变更同步维护测试及说明。
- Python 使用四空格缩进，新增或修改的接口补齐参数和返回值类型，保留具体业务类型。
- 工具和文件操作基于实际 cwd；workspace_path 不会切换目录，也不是沙箱。启动脚本须保留调用者 cwd。
- 配置测试必须隔离 settings.root、缓存、环境变量和 Skills，方式见 [配置测试](../docs/omt/tests/session-and-config.md)。
- Python 静态检查覆盖修改文件，先相关测试再全量离线测试，命令见 [开发说明](../docs/development.md)。
- MCP 默认为空。配置测试验证 CLI/API 的独立环境变量及错误处理，使用假命令或 HTTP 替身。

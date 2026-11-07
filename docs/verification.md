# 迁移验证记录

日期：2026-11-07。验证对象为当前 monorepo 工作区，不包含真实用户模型或资料联调。

## 已完成

| 检查 | 实际结果 |
| --- | --- |
| 根脚本 unittest | 15 项：14 通过、1 项因本机 TCP 权限跳过；覆盖参数、cwd、启动顺序、信号、失败及子进程清理 |
| backend 全量 pytest | 729 通过，4 条现有 LangGraph 流协议实验性警告 |
| knowledge_base unittest | 153 通过，包含真实 stdio MCP 握手和启动构建协议测试 |
| knowledge_base evals/tests | 77 通过 |
| frontend Vitest | 10 个文件、171 项通过 |
| frontend typecheck / lint | 均通过 |
| ShellCheck | 根 scripts 的所有 Bash 入口与 common.sh 通过 |
| Python 源码静态检查 | 两个后端配置文件和两个新 Python 入口均为 0 错误、0 警告 |
| Python 测试静态检查 | 后端两个修改测试文件为 0 错误、39 条动态类型/风格警告；新脚本测试为 0 错误、36 条 Mock/动态数据/风格警告 |
| 文档引用 | 迁移后的 52 份文档相对链接目标均存在；前后端 API 契约只保留一份 |
| CI 配置 | 根 workflow 的 YAML 解析通过，包含 scripts/backend/knowledge-base/frontend 四个 job；尚未在远端运行 |
| Git 历史 | 三个源 main 均是新 main 的祖先，10 个源本地分支及原远端跟踪引用逐一核对原 SHA |
| 原仓库及数据 | 原三个工作区保持干净；锁文件、评估 JSON 和数据库展示快照逐字节一致 |

共通过 1,144 项测试，另 1 项跳过。相关执行命令见 [开发说明](development.md)。Python 依赖按原锁文件离线安装；前端使用原锁文件执行离线 npm ci，未变更依赖版本。

## 受限环境说明

当前执行环境禁止创建/监听本机 TCP socket，并影响异步线程唤醒及 Node 的同步子进程结果读取。普通异步测试曾挂起；通过仓库外的临时事件循环轮询支持运行 backend 与 knowledge_base 的完整用例及其子进程，产品源码和测试断言未修改。验证结束后，虚拟环境中的临时支持文件已移除，不随仓库分发。

以下检查已尝试，但不能在本环境宣称通过：

- `npm run build`：Turbopack 内部绑定端口时报 Operation not permitted。
- `npm run build -- --webpack`：Node spawnSync 报 EPERM，Next.js 无法读取 TypeScript `--showConfig` 的结果；单独的 tsc 检查已通过。compile 模式也遇到同一限制。
- `npm run test:proxy`：本机 HTTP 替身监听 127.0.0.1 时返回 listen EPERM。
- 根脚本真实 TCP 集成项：因同一权限限制明确跳过；其他进程测试使用隔离的就绪替身。

完整构建和真实端口代理测试保留在 CI 中，应在普通开发环境或远端 CI 再执行。不请求真实模型，不启动用户实际配置的 Agent，不改写 ~/.omt 或已有知识库。

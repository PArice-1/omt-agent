# 安装与启动脚本测试

## 对象与目的

源码为 [scripts](../../scripts/)，测试为 [test_scripts.py](../../tests/test_scripts.py)。保证从任意工作目录、含空格的仓库路径启动时，依赖位置、Agent cwd、前后端地址及进程生命周期正确，且未启用插件时无需知识库目录。

## 场景

| 场景 | 输入 / 前置条件 | 预期 |
| --- | --- | --- |
| 帮助与缺依赖 | 未安装后端，执行 --help 或启动 CLI | 帮助可读；启动给出 setup 指引，不安装依赖或拉起服务 |
| CLI 参数与 cwd | 外部 workspace、含空格仓库、--plain | 转发参数，安装位置使用 backend，实际 cwd 保持 workspace |
| API 参数 | 非法/缺失端口或未知参数 | 启动前拒绝；正常端口及单 worker/回环参数由 Web 进程测试验证 |
| 默认安装与可选插件 | setup 无参数 / --with-knowledge-base | 分别只安装 backend/frontend，或额外安装插件，均使用锁文件 |
| 插件配置生成 | 含空格及中文的源/存储路径，构建开关开关两种情况 | 输出合法 JSON、绝对命令和 cwd；默认不构建，不创建资料或存储 |
| stdio 包装 | 临时安装的插件、传入存储路径 | 插件 cwd 固定，参数转发且 stdout 无额外文本 |
| Web 正常启动与信号 | API 就绪替身、Next 替身、SIGINT/SIGTERM/SIGHUP | 顺序正确，API 保留 cwd、Next 使用 frontend 目录，地址与端口一致；只清理本次进程组及其子进程 |
| Web 失败清理 | API 提前退出、API 超时、Next 失败 | 非零退出，前置失败不启动 Next，已经创建的进程及子进程关闭 |
| 领进程先退出 | uv/npm 型领进程退出，服务子进程需要短暂清理 | 继续等待整个进程组，子进程能完成退出写入，宽限期后才强杀残留进程 |
| 参数边界 | 非法端口、端口相同、非有限 timeout | 创建子进程前拒绝 |
| HTTP 存活与端口占用 | 隔离本机 HTTP 假 API，模型 ready=false，或已有端口 | 只以 /health 允许前端启动，已有端口拒绝；无 TCP 权限的环境明确跳过 |

HealthProbeTests 单独用 HTTP 响应替身验证只请求 /health、提前退出、超时以及占用端口错误转换。进程编排测试用文件就绪替身隔离网络，同时运行真实测试子进程并验证退出后的存活状态；真实 TCP 集成项在普通开发环境和 CI 中运行。

## 隔离与运行

测试复制脚本到 TemporaryDirectory，提供假 uv/npm/node 和临时安装目录；日志、cwd、显式配置的数据目录均隔离。假 API/Next 只休眠或返回固定 JSON，不导入 backend、不连接真实模型，也不修改原仓库环境。进程只针对测试创建的 PID/进程组发信号。

```bash
python3 -m unittest discover -s tests -v
shellcheck -x -P SCRIPTDIR scripts/*.sh scripts/lib/common.sh
```

## 限制

替身不证明真实模型、Ollama 或用户配置可用；TCP 测试通过不等于真实 backend 联调。真实代理和 SSE 转发由 frontend 的 test:proxy 验证。脚本依赖 POSIX 进程组，不支持原生 Windows shell。

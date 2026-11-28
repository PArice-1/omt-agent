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

## Docker 测试入口

根目录的 [compose.yaml](../../compose.yaml) 和 [Dockerfile](../../Dockerfile) 提供独立 Linux 测试环境。Docker 构建会拉取基础镜像及锁定依赖，不纳入默认离线套件。请在空闲 3000 端口、可信的开发机器上用独立项目名验证：

```bash
docker compose -p omt-compose-check config --quiet
docker compose -p omt-compose-check up --build -d --wait
curl -fsS http://127.0.0.1:3000/api/omt/health
curl -fsS http://127.0.0.1:3000/api/omt/runtime
docker compose -p omt-compose-check exec -T backend sh -ec 'test "$(id -u)" -ne 0; test "$PWD" = /sandbox/workspace; touch .compose-check'
```

如果开发机本身已安装前端依赖和 Playwright Chromium，可在停止测试容器前，从仓库根目录运行真实浏览器检查：

```bash
node frontend/tests/integration/compose-connect.mjs
docker compose -p omt-compose-check down -v
```

[浏览器检查](../../frontend/tests/integration/compose-connect.mjs)在 `127.0.0.1` 和 `localhost` 分别点击「未连接」→「连接本机后端」，断言尚未配置模型时仍能连接，且不请求会话。默认使用宿主机端口 3000；若验证实例改用了其他端口，可传入端口号。未运行浏览器检查也应执行上面的清理命令。

预期健康响应为 `{"status":"ok"}`，新的命名卷里运行状态为未配置；后端非 root 且能够写入独立工作目录。只有回环 3000 对宿主机发布，8000 仅在共享的容器网络内使用。此过程不读写真实 `~/.omt`、不执行用户代码或调用模型。清理只删除这次测试项目的卷，不应使用已有数据的项目名。首次保存模型、真实凭据与聊天不在此冒烟测试内。

## OMT 评测注册与执行入口

`evals/register_datasets.py` 按 suite 查找、创建或复用 LangSmith Dataset；`evals/main.py` 只评测已注册的样例，且调用真实 OMT 需要显式传入 `--live`。两者分别运行，详见 [评测说明](../evals.md)。

测试用内存 Dataset 验证单任务对象和任务数组、重复注册、追加、冲突保护及显式更新评分名单。用真实 LangSmith 异步 runner 验证同一 suite 内不同样例选择不同评分器、trial 并发上限和逐条/汇总反馈；用协程同步点验证同一 trial 内两个评分器确实并发且失败互不影响。命令行报告只写临时目录，HTTP 适配器用传输替身验证独立会话和原始回答。整个测试套件不访问真实网络或用户工作区。

```bash
cd evals
uv run --frozen --no-sync python -m pytest tests -q
```

## 知识库 BM25 评估入口

`knowledge_base/evals/run_bm25.py` 提供 `python -m evals.run_bm25`：显式指定向量 JSON 报告，读取对应静止 Qdrant 快照的临时副本，复用问题及全部正相关 ID，导出新的 JSON/Markdown 对照报告。不会调用模型、改写原数据库或覆盖旧报告；K 和片段预算继承基线。此入口不属于需要 `--live` 的 OMT 评测。

`knowledge_base/evals/tests/test_bm25.py` 使用临时测试数据库和固定排名验证实际 BM25 检索、参数传递、评分/导出、源数据库不变及失败保护。默认测试不访问已保存的展示快照。详细场景见[知识库评估说明](../knowledge_base/evaluation.md#自动测试)。

```bash
uv run --frozen --no-sync --directory knowledge_base --group eval python -m unittest evals.tests.test_bm25 -v
```

## 限制

替身不证明真实模型、Ollama 或用户配置可用；TCP 测试通过不等于真实 backend 联调。真实代理和 SSE 转发由 frontend 的 test:proxy 验证。脚本依赖 POSIX 进程组，不支持原生 Windows shell。

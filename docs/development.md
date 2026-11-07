# 开发、配置与验证

以下命令从仓库根目录执行。Python 3.12+、Node.js 22.19+；根 .python-version / .nvmrc 提供默认版本。Python 包独立安装，npm 依赖保持在 frontend。

## 安装与配置

```bash
./scripts/setup.sh                       # backend + frontend
./scripts/setup.sh --with-knowledge-base # 额外安装插件
uv sync --frozen --group eval --project knowledge_base # 需要运行评估测试时
```

安装会严格使用现有锁文件。修改 Python 依赖使用 uv 并同步对应 uv.lock，前端使用 npm 并同步 package-lock.json。只有进入 backend 或 knowledge_base 后执行 uv run，或显式使用 --project / --directory，才会定位到对应项目。

| 配置 | 生效范围 |
| --- | --- |
| `~/.omt/agent/{settings,auth,model-store}.json` | 共用模型目录、凭据和默认选择 |
| `~/.omt/agent/state/omt.sqlite` | 默认会话索引及检查点，不随代码迁移 |
| `OMT_CLI_*` / `OMT_API_*` | 各自入口配置；DB_PATH、SKILL_ROOTS、MCP_SERVERS 等见后端文档 |
| `OMT_API_PORT` / `OMT_WEB_PORT` | 根启动脚本默认端口，命令行可覆盖 |
| `frontend/.env.local` 的 `OMT_BACKEND_URL` | 独立运行 Next.js 时的本机上游；start-web 为本次进程直接注入地址 |

脚本保留 CLI/API 的实际 cwd。MCP 默认关闭，安装插件也不会隐式启用；启用方式见 [插件接入](knowledge_base/plugin.md)。根目录不会自动加载 .env。

## 默认离线检查

```bash
python3 -m unittest discover -s tests -v
shellcheck -x -P SCRIPTDIR scripts/*.sh scripts/lib/common.sh
uv run --frozen --no-sync --project backend pytest -q backend/tests --tb=no
uv run --frozen --no-sync --directory knowledge_base --group eval python -m unittest discover -s tests -v
uv run --frozen --no-sync --directory knowledge_base --group eval python -m unittest discover -s evals/tests -v
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:proxy
git diff --check
```

脚本测试只启动测试替身，后端使用假模型和临时 SQLite，知识库 mock 向量模型，代理测试使用本机 HTTP 替身。测试不会读取真实模型凭据、请求 Ollama 或改写知识库展示快照。uv 的 --no-sync 要求先按对应锁文件安装依赖。

修改 Python 文件后运行 basedpyright。backend/pyrightconfig.json 指定了本模块的 .venv 和 src 导入路径，可在 backend 目录检查修改的源码/测试；根脚本按 Python 3.12 检查。前端代码或视觉行为变更时按 [前端说明](../frontend/README.md) 运行 Playwright；纯迁移使用已有单元、类型、构建和真实代理冒烟检查。此次实际结果与环境限制见 [迁移验证](verification.md)。

CI 在根 `.github/workflows/ci.yml` 中分开验证脚本、backend、knowledge_base 和 frontend。权限、真实网络/模型联调及浏览器系统库限制应在交付记录明确说明，不用假模型通过替代真实联调结论。

## 文档维护

专题统一放在 docs/omt、docs/frontend、docs/knowledge_base。前后端契约只维护 docs/omt/frontend-api.md；后端测试说明保留 docs/omt/tests。新增脚本的测试说明放在 docs/tests。

资料目录、虚拟环境、node_modules、用户配置和原始评估下载均被忽略；已有评估报告与数据库展示快照继续跟踪。新增文件交付前检查 Git 跟踪与忽略状态。

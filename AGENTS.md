# Monorepo 协作规范

适用于整个仓库；模块补充规则见 backend/AGENTS.md、frontend/AGENTS.md。

## 开始修改前

- 查看 Git 状态并保留无关修改。提交、推送、发布及破坏性 Git 操作须有当前会话授权。
- 定位入口见 [文档导航](docs/README.md)。涉及目录、依赖、启动或配置时先读 [整体架构](docs/architecture.md) 和 [开发说明](docs/development.md)。
- 修改后端模型、会话、工具或流时先读 [后端架构](docs/omt/architecture.md)；修改前后端接入时读 [唯一 API 契约](docs/omt/frontend-api.md)。
- 修改测试先读对应说明；新增脚本行为说明写入 [脚本测试](docs/tests/scripts.md)，后端测试遵守 [后端测试规范](docs/omt/tests/README.md)。

## 维护约定

- Git 提交信息的标题和正文使用中文描述改动；type、scope 和代码标识符可沿用英文，例如 `feat(knowledge_base): 支持按配置启用知识库插件`。
- 文档、注释和测试说明默认中文，代码标识符沿用英文。新增或修改的重要函数和类必须补充中文 docstring 或说明注释，写清职责、输入输出及必要的副作用。
- 重要参数必须在 docstring 或附近注释中说明用途、业务含义，以及适用的单位、范围、默认值和生效时机；注释解释原因和约束，避免只复述名称或类型。
- backend、knowledge_base 独立使用各自的 pyproject.toml 与 uv.lock；frontend 沿用 npm 和 package-lock.json。修改依赖同步锁文件。
- knowledge_base 是可选 MCP 插件。backend 通过显式 MCP 配置接入，保持未安装插件时可运行。
- 权威文档统一放在根 docs，模块 README 负责定位和导航；调整路径时核对图片、源码、测试及协作规范链接。
- 测试围绕模块提供的能力和对外契约组织，通过公开入口验证可观察的结果、状态变化及必要副作用，覆盖主要使用场景、边界和失败路径；需要时串联模块内多个函数或类验证完整流程。
- 函数级单元测试可补充算法和边界细节，不能替代模块能力验证；不能只验证内部方法被调用或照搬实现步骤。行为变更同步维护相关测试和中文说明，验证命令与隔离要求见开发说明，如实报告未执行或失败的检查。
- 默认测试使用替身、临时文件和测试创建的进程。真实模型请求、用户数据写入和真实后端交互须有专门授权。
- 凭据、用户配置、运行数据库和本地依赖保持在 Git 之外；knowledge_base/evals/data/storage 是明确保留的展示快照，不能被通配规则误删或隐藏。

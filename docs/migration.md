# Monorepo 迁移记录

迁移日期：2026-11-07。新仓库使用原有 omt-monorepo 根 Git，统一管理以下目录：

| 原目录 | 当前目录 | 导入的 main 提交 |
| --- | --- | --- |
| OMT | backend | `41b69c6777d78b22cc791ed2c72290fa66381e2d` |
| rag-mcp | knowledge_base | `67c89907909290bd29d339cba8b3d97b23b81ff8` |
| omt-frontend | frontend | `48c489e2aaa1a7a0ce3f5052fd3fd4d8aebbd852` |

## 历史与恢复依据

使用不压缩历史的 git subtree 导入三个 main，原提交 ID 保留，均为新 main 的祖先。各项目原本地分支保留在 legacy/backend/*、legacy/knowledge_base/*、legacy/frontend/*；原远端跟踪引用归档在 refs/archive/<模块>/remotes/*，并未设置或推送新的远端。

完整源引用见 [源提交清单](migration-sources.json)。可以使用 git merge-base --is-ancestor 核对三个源 HEAD，使用 git branch --list 'legacy/*' 查看旧分支。历史提交仍保留原项目内路径；当前文件增加了模块前缀，因此跨导入点追踪文件时需要结合源分支查看原路径。

源目录和源仓库未修改、未删除。迁入的是 Git 跟踪内容；原虚拟环境、用户配置、未跟踪/被忽略的 samples、draft、knowledge-base 和本机数据库仍留在原位置。新环境按原锁文件安装。知识库已经跟踪的评估报告与展示快照完整保留。

## 内容调整

- 后端文档移到 docs/omt，知识库专题移到 docs/knowledge_base，前端架构和图片移到 docs/frontend；相对引用同步调整。
- 原前端 docs/frontend-api.md 的跨仓库软链接收敛到 docs/omt/frontend-api.md，接口定义只有一份。
- CLI/API 继承共用的空 MCP 默认值，去掉原机器绝对路径；插件显式启用，依赖和命令名保留。
- 根 scripts 提供安装、CLI、API、Web 和插件入口；根 .github/workflows 管理各模块 CI。
- 模型 JSON 与会话库继续位于 ~/.omt；迁移不改写会话中的 workspace_path。在新目录启动时会话列表按新 cwd 过滤，原目录的会话仍须在对应原 cwd 使用。

后续确认新仓库使用正常后，可由操作者决定如何归档原目录以及配置新远端。

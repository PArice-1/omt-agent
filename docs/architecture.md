# OMT Frontend 架构

## 目标与状态
第一版面向可信本机、单用户，采用 Next.js App Router + TypeScript strict。
用户确认浅蓝色、简洁美观的界面；令牌仅存内存，刷新后重新输入。
本文件描述第一版已实现的结构与行为。接口事实以 [frontend-api.md](frontend-api.md) 为准。

## 模块导航与依赖
```
app/page → features/workspace/workspace
                    ├→ connection（内存凭据和连接）
                    ├→ workspace/model（状态与操作）
                    │     └→ lib/omt-api（契约、校验、请求）
                    └→ 展示组件（props 与回调）
浏览器 API 客户端 → /api/omt/* → Next.js Node Route Handler → 固定本机后端
```

- `src/app/`：页面、布局、全局样式和代理路由。页面不承载业务编排。
- `src/lib/omt-api/`：Zod schema 是响应类型的单一来源；集中导出类型与 OmtClient interface。客户端接受 getToken/fetch 依赖，不依赖 React。
- `src/features/workspace/model/`：框架无关的工作台控制器，向调用方提供状态快照、订阅和显式操作；隐藏连接世代、去重、锁、历史替换及错误分类。
- `src/features/connection/`：令牌输入界面。实际令牌只在控制器私有内存中，不进入可渲染状态、持久存储或日志。以后增加存储时在连接流程接入，UI 与 API 函数无需直接访问存储。
- `src/features/workspace/components/`：侧栏、消息、输入框、提示等展示模块，不直接 fetch。
- `src/features/workspace/workspace.tsx`：React 组合入口，使用 useSyncExternalStore 订阅控制器。
- `src/features/workspace/hooks/use-message-scroll.ts`：视图内滚动策略，发送/输出/历史同步时定位到底部，普通更新保留用户阅读位置。
- `src/lib/server/`：固定上游代理与本机地址校验，仅供 Route Handler 使用。

控制器从 React 通过 useState 建立实例，使用 useSyncExternalStore 订阅，SSR 初始快照不包含凭据。
控制器持有独立 QueryClient，用 fetchQuery 对同会话 GET 去重；不挂载自动查询观察器，无焦点刷新、轮询或隐式重试。状态在工作台生命周期中保留，不随会话视图卸载。
基础布局使用 Tailwind CSS 及语义化 CSS；首版使用原生按钮、details 和 dialog，暂不引入整套 UI/AI SDK，避免与已有后端能力重复。

## 数据流与不变量
1. 用户提交令牌 → 使用会话列表验证认证 → 保存列表并选择会话 → 读取完整历史。
2. 点击新建时立即 POST，允许可选标题；服务端返回 ID 后才更新选择。创建响应丢失时提示先刷新列表确认，不自动重试。
3. 历史未读取成功、正在刷新列表或存在未知结果时禁止发送；允许发送后先同步取得操作锁，再发送本轮原始输入。全局仅允许一条已知本地执行。
4. 运行成功后立即记录 completed、answer、warnings，再独立刷新完整历史和列表。普通成功不展示“本轮已完成”横幅或运行 ID，直接呈现回答并滚动至最新输出；非致命 warnings 仍展示。若运行期间已有列表读取，等待其结束后再请求完成后的新快照。刷新失败仍为完成，保留临时回答；历史刷新成功后移除临时内容，避免重复。同步完成前禁用发送，避免草稿尚未清除时重复提交。
5. 所有响应绑定发起时 session_id 与连接世代。切换会话不会串写；断开或更换连接后丢弃旧响应。
6. POST 无自动重试；不在渲染或 effect 中创建会话、发送消息。不轮询运行状态，不在运行中读取该会话历史。
7. 完整历史按返回顺序替换。调用和结果有 ID 时关联，无 ID 保留原样。正文与工具输出不作为可信 HTML。
8. 时间显式按 UTC 格式解析后本地化，不直接将数据库字符串交给 Date 猜测时区。

## 状态与错误
运行状态为 idle / sending / completed / rejected / needs_attention / unknown。这些是内存中的前端观察，不是后端会话字段。
- 明确的认证、校验、busy、容量拒绝作为 rejected；run_failed / session_incomplete 需要人工检查。
- 网络断开、无法解析、存储/内部错误等可能已产生副作用，进入 unknown。
- unknown 不自动解锁重发。用户可显式读取历史，成功后检查并确认允许继续；此确认不证明丢失请求的结果，界面明确说明。
- 执行成功后的刷新错误与执行错误分离；GET 失败只说明对应读取失败，不附加“执行结果不明”的泛化文案。历史刷新返回 incomplete 也不改写已确认的 completed，而是保持历史不可用、阻止继续发送。异常时保留 run_id 用于诊断，不记录敏感正文。
- `connection` 表示内存凭据/认证流程，不是持续在线连接；`backendStatus` 记录最近请求的可用性观察。网络、代理或响应异常时显示“连接待检查”，有效响应后恢复；busy/容量等明确业务拒绝不视为断线。使用请求序号和连接世代，避免旧请求晚到覆盖新观察。
- 连接设置中的“检查连接”只显式读取会话列表，不轮询、不重发消息；检查成功也不解除 unknown 的运行保护。
- 顶部提示支持关闭，关闭只清除提示内容，不改变连接观察或运行状态。列表刷新提示标记来源，后续成功刷新列表时清理该旧提示，保留其他来源的提醒。
- 未加载或读取失败的历史不伪装为空历史，不允许盲目追加；同会话读取去重。
- 已知执行或创建进行中禁止更换/断开连接，避免丢失本地执行跟踪。结果不明时允许用户在阅读风险提示后主动断开，清除本地状态不等于停止后端；页面刷新同样会丢失内存观察，界面有提示。

## 服务端、配置与安全
- dev/start 默认绑定 127.0.0.1；不适用于公网或多用户部署。
- `OMT_BACKEND_URL` 为服务端配置，默认 http://127.0.0.1:8000，只允许 http(s) 本机回环地址，无凭据、查询或自定义路径。
- 代理仅允许已知 health/sessions/messages/runs 路径及 GET/POST 方法，禁止任意目标 URL、重定向及 Cookie 转发。
- 请求 Bearer 只转发到配置的固定上游；禁止用 NEXT_PUBLIC 配置保存秘密。浏览器跨来源 POST 被拒绝。
- Undici 单次请求禁用 headers/body 超时以等待长执行，不使用重试 Agent、不传浏览器断连作为后端取消信号。连接失败仍会结束请求。
- Next.js 可能把 Request.url 归一化为内部 localhost origin；浏览器同源校验以原始 Host 和协议为准，并且 Host 本身必须是回环地址。拒绝外部 Host，降低本机 DNS rebinding 风险；不信任 x-forwarded-host 作为公开入口。
- 浏览器响应与上游请求均禁用缓存；代理错误显式标为结果可能不明，不声称已取消。部署到有请求时限的平台前必须重新设计。
- Markdown 使用 react-markdown + GFM，跳过原始 HTML，外部图片改为说明文字以避免自动联网；工具输入输出用转义文本/JSON。外链使用安全 rel。

## 视觉与可读性
- 浅蓝色用于页面、卡片和装饰背景，不以淡蓝文字承载阅读内容；正文采用深蓝灰，操作采用明确的品牌蓝。
- 颜色集中在 `src/app/globals.css` 的语义变量中管理：正文、辅助文字、占位文字、操作色、边框及成功/警告/错误各有对应角色，避免散落近似浅色。
- 关键文字（包括占位说明、时间、警告及按钮标签）以至少 4.5:1 的对比度为目标。禁用态使用独立前景/背景，不以整体降低 opacity 使内容消失。
- 正文和输入采用 14px，辅助文字通常 12–13px，最小提示为 11px；窄屏不退回 8–9px 的小字。
- 阅读区域使用实色表面，使颜色组合和回归测试可预测；渐变仅用于无正文的装饰。短视口内容超出时从顶部可滚动，装饰图标不被挤扁。
- `tests/e2e/contrast.spec.ts` 检查桌面、窄屏、悬停、连接弹窗、禁用输入及消息/工具/非致命警告的实际计算颜色。它是关键场景回归，不等同于完整的无障碍认证。

## 测试策略
- Vitest：API 请求契约、运行时校验、错误、单次发送；纯逻辑与控制器状态、锁、竞态和连接隔离。
- React Testing Library + MSW：真实 API 客户端下的连接、创建、发送、历史替换、异常状态与安全渲染。
- 代理冒烟测试：实际构建的 Next.js + 随机端口本机 HTTP 替身，验证 Route Handler 的请求来源、编码 ID、Bearer/JSON 转发及禁止 Cookie 转发。测试进程结束后关闭服务。
- Playwright：使用路由 mock 的真实浏览器关键流程与窄屏布局，不连接真实后端。`feedback.spec.ts` 复现执行成功后列表刷新失败、关闭提示和只读检查；`scroll.spec.ts` 覆盖向上阅读后发送、临时回答、完整历史同步的到底行为，并验证普通弹窗更新不抢走阅读位置。
- lint、tsc、Next build 是交付检查；启动和命令见 [README](../README.md)。

## 扩展方式
- 新增接口：先更新经过确认的契约文档，再增加 schema、OmtClient 方法及测试，随后接入对应功能。
- 新增功能：优先新增独立 feature，只依赖客户端公开 interface；确有复用再提取公共模块。
- 增加令牌持久化：先确认安全策略，再为连接模块增加存储实现；现在不提前搭建多种存储。
- 增加流式、取消、多用户等能力必须先确认后端契约，不能仅由 UI 模拟。

## 参考与取舍
- [Vercel Chatbot](https://github.com/vercel/chatbot)：参考页面与聊天布局，不引入其模型、数据库及认证体系。
- [assistant-ui](https://github.com/assistant-ui/assistant-ui)：参考组合式消息和工具展示，不直接接管其 runtime。
- [Next.js Route Handlers](https://nextjs.org/docs/app/getting-started/route-handlers)：同源代理采用 Node runtime。
- [Undici Dispatcher](https://github.com/nodejs/undici/blob/main/docs/docs/api/Dispatcher.md)：明确配置长请求超时。

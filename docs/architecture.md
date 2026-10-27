# OMT Frontend 架构

## 目标与状态
第一版面向可信本机、单用户，采用 Next.js App Router + TypeScript strict。
用户确认浅蓝色、简洁美观的界面；当前按无认证契约连接，无令牌输入、保存或登录流程。
本文件描述已实现的结构与行为，包含运行配置、模型切换及 OMT v1 SSE。接口事实以 [frontend-api.md](frontend-api.md) 为准；该文件是后端文档的软链接，不在前端仓库中修改其内容。

## 模块导航与依赖
```
app/page → features/workspace/workspace
                    ├→ connection（本机连接与检查）
                    ├→ runtime（进程级配置与展示）
                    ├→ workspace/model（状态与操作）
                    │     └→ lib/omt-api（契约、校验、请求）
                    └→ 展示组件（props 与回调）
浏览器 API 客户端 → /api/omt/* → Next.js Node Route Handler → 固定本机后端
```

- `src/app/`：页面、布局、全局样式和代理路由。页面不承载业务编排。
- `src/lib/omt-api/`：Zod schema 是响应类型的单一来源；集中导出类型与 OmtClient interface。客户端接受可选 baseUrl/fetch 依赖，不依赖 React，不发送 Authorization。`events.ts` 校验 OMT v1 信封及已知事件 data；`stream.ts` 使用 fetch/ReadableStream 增量解析 SSE，不使用整包 text/json 读取成功流。
- `src/features/workspace/model/`：框架无关的工作台控制器，向调用方提供状态快照、订阅和显式操作；隐藏连接世代、去重、锁、历史替换及错误分类。
- `src/features/connection/`：无令牌的连接界面，提供显式连接、只读检查与断开操作，并提示仅供可信本机使用。
- `src/features/runtime/`：独立的 RuntimeController 管理全进程运行状态、厂商/本地模型目录、配置预览/确认及临时切换；与所选会话无关。密码输入仅在弹窗内短暂保存，提交前清空；Key 只经客户端提交给固定本机上游，不进入控制器快照、浏览器存储或日志。保存结果与启用结果分别展示。`runtime-settings.tsx` 只承载从左侧栏进入的厂商配置弹窗；`runtime-controls.tsx` 提供输入框底部的模型/思考强度下拉及状态反馈，通过 props 回调接入控制器，不直接请求后端。
- `src/features/workspace/components/`：侧栏、消息、输入框、提示等展示模块，不直接 fetch。
- `src/features/workspace/workspace.tsx`：React 组合入口，使用 useSyncExternalStore 订阅控制器。
- `src/features/workspace/model/stream-state.ts`：纯事件投影，以 message_id 累积正文/独立 reasoning，以 tool_call_id 累积工具输入、JSON 进度和终态，不按名称合并。
- `src/features/workspace/hooks/use-message-scroll.ts`：视图内滚动策略，显式发送时恢复跟随；增量输出、完成及历史同步仅在用户原本接近底部时跟随，不抢走向上阅读位置。
- `src/lib/server/`：固定上游代理与本机地址校验，仅供 Route Handler 使用。

控制器从 React 通过 useState 建立实例，使用 useSyncExternalStore 分别订阅工作台和运行设置。SSR 初始快照为未连接，挂载 effect 仅去重读取 runtime/厂商/本地模型目录，不自动连接会话、创建、保存配置或执行消息。会话接入仍由用户显式触发。
控制器持有独立 QueryClient，用 fetchQuery 对同会话 GET 去重；不挂载自动查询观察器，无焦点刷新、轮询或隐式重试。状态在工作台生命周期中保留，不随会话视图卸载。
Composer 使用 controls/settingsFeedback 插槽组合运行设置，不绑定具体 API 或 RuntimeController；Sidebar 通过 onModels 打开配置。顶部不展示模型设置栏，窄屏配置入口随侧栏展开，日常切换始终位于输入框内。
基础布局使用 Tailwind CSS 及语义化 CSS；首版使用原生按钮、details 和 dialog，暂不引入整套 UI/AI SDK，避免与已有后端能力重复。

## 数据流与不变量
1. 打开页面只读检查 runtime 与目录；未配置或未就绪时在输入区提示从左侧“添加模型”进入厂商配置；日常模型/强度切换直接在输入框底部操作。用户点击连接（无需令牌）→ 再检查 runtime → 就绪后读取会话列表并选择/加载历史；未就绪时允许连接配置入口，不请求会话接口。配置流程是厂商 → Key/复用本地凭据 → 获取预览 → 选模型 → 明确确认保存并尝试启用。只有返回结果中的运行状态表示实际生效配置，HTTP 200 不等于全部成功。
2. 点击新建时立即 POST，允许可选标题；服务端返回 ID 后才更新选择。创建响应丢失时提示先刷新列表确认，不自动重试。
3. 历史未读取成功、正在刷新列表或存在未知结果时禁止发送；允许发送后先同步取得操作锁，再发送本轮原始输入。全局仅允许一条已知本地执行。
4. 发送仅提交本轮 message 到 `/runs/stream`，每请求持有独立 AbortController。run.started 绑定 session/run 和 thinking 快照；助手、工具终态不结束整轮。只有 run.completed 确认成功，answer 核对/替换最后的回答而非重复追加；若最后只有工具记录，保留先前计划并建立缺失的最终回答。随后独立刷新完整历史及列表，历史成功后一次替换历史并清除临时输入/消息/工具。若运行期间已有列表读取，等待其结束后再请求完成后的新快照。刷新失败仍为完成，保留过程与回答，不重新执行。同步完成前禁用发送。
5. 会话操作的所有响应绑定发起时 session_id 与连接世代。切换会话不会串写；断开或更换连接后丢弃旧响应。
6. POST 无自动重试；不在渲染或 effect 中创建会话、发送消息。不轮询运行状态，不在运行中读取该会话历史。
7. 完整历史按返回顺序替换，保留可选 message_id/reasoning，缺少可选字段的旧历史仍可展示。调用和结果有 ID 时关联，无 ID 保留原样。正文、reasoning、工具输入/JSON 进度/结果均不作为可信 HTML。
8. 时间显式按 UTC 格式解析后本地化，不直接将数据库字符串交给 Date 猜测时区。

## 状态与错误
运行状态为 idle / sending / completed / rejected / needs_attention / failed / cancelled / unknown。这些是内存中的前端观察，不是后端会话字段。receiving 表示同一流请求尚未结束，stopping 表示已请求停止接收；runId、thinking 快照及临时 items 保存在原 session 下。终态已收到但连接仍未清理时也不允许下一轮。
- 接纳前解析普通 HTTP JSON 错误；接纳后的 run.failed/cancelled 是已确认的失败/取消，保留过程并保护当前会话，不自动重发。工具失败可由模型处理后整轮成功。
- 停止按钮只 abort 对应请求；显示已停止接收/正在终止，不保证工具立即停止或副作用回滚。未收到运行终态的 EOF、网络/解析异常及主动停止均为 unknown，不宣称确定取消。
- RuntimeController 的 pending 对读取/预览/确认/切换同步加锁；本地执行时不允许配置切换。服务端 busy/changing 仅是快照，可显式重新检查，不自动轮询。切换期间保留旧生效值，成功后使用返回的完整 RuntimeResponse；失败/忙碌拒绝不把请求选项当成生效状态。请求 level 与实际 reasoning_effort 分开展示，实际降为 none 时提示回退。
- 明确的校验、not_found、busy、容量拒绝作为 rejected；run_failed / session_incomplete 需要人工检查。契约外错误（包括意外的 unauthorized）按 unknown 保留执行跟踪，不触发令牌失效或清空状态。
- 接纳前已知后端 JSON 拒绝（包括存储/内部错误）由 RunAdmissionError 标记，不宣称本轮已执行；session_incomplete 仍需人工检查。代理错误可能掩盖已接纳的执行，与网络/协议异常一样进入 unknown。接纳后失败必须以流内终态区分。
- unknown 不自动解锁重发。用户可显式读取历史，成功后检查并确认允许继续；此确认不证明丢失请求的结果，界面明确说明。
- 执行成功后的刷新错误与执行错误分离；GET 失败只说明对应读取失败，不附加“执行结果不明”的泛化文案。历史刷新返回 incomplete 也不改写已确认的 completed，而是保持历史不可用、阻止继续发送。异常时保留 run_id 用于诊断，不记录敏感正文。
- `connection` 表示本页工作台是否已接入后端，不是认证状态或持续在线连接；`backendStatus` 记录最近请求的可用性观察。网络、代理或响应异常时显示“连接待检查”，有效响应后恢复；busy/容量等明确业务拒绝不视为断线。使用请求序号和连接世代，避免旧请求晚到覆盖新观察。
- 连接设置中的“检查连接”显式读取运行状态/目录，就绪时再读取会话列表，不轮询、不重发消息；检查成功也不解除 unknown 的运行保护。
- 顶部提示支持关闭，关闭只清除提示内容，不改变连接观察或运行状态。列表刷新提示标记来源，后续成功刷新列表时清理该旧提示，保留其他来源的提醒。
- 未加载或读取失败的历史不伪装为空历史，不允许盲目追加；同会话读取去重。
- 已知执行或创建进行中禁止断开连接，避免丢失本地执行跟踪；已接入时仅允许只读检查，不允许重复 connect 清空跟踪。结果不明时允许用户在阅读风险提示后主动断开，清除本地状态不等于停止后端；页面刷新同样会丢失内存观察，界面有提示。

## 服务端、配置与安全
- dev/start 默认绑定 127.0.0.1；不适用于公网或多用户部署。
- `OMT_BACKEND_URL` 为服务端配置，默认 http://127.0.0.1:8000，只允许 http(s) 本机回环地址，无凭据、查询或自定义路径。
- 代理只允许契约中的 health、runtime、providers、models、model-logins 及会话/历史/运行路径，逐路径限制 GET/POST/PUT。禁止任意目标 URL、重定向及 Cookie 转发。
- 业务接口及 health 均不要求认证。代理不校验 Bearer，也不转发传入的 Authorization 或 Cookie；禁止用 NEXT_PUBLIC 配置保存秘密。无认证不等于开放跨域，浏览器跨来源请求仍被拒绝。后端与代理仅面向可信本机。
- Undici 单次请求禁用 headers/body 超时以等待长执行，不使用重试 Agent。仅 SSE 路径传递浏览器 Request.signal，响应以带背压的 ReadableStream 逐块转发，取消下游流同时取消上游 reader，并设置 X-Accel-Buffering: no。非流式兼容路径维持原断连语义，不声称能够取消。
- SSE 使用流式 TextDecoder 处理跨块 UTF-8，保留半帧、按空行拆帧并处理注释心跳；校验版本、event/type、session/run 关联及严格递增但不要求连续的 seq。未知类型验证信封后忽略，不视为成功；无重连、补发或后台查询。单帧限制 2 MiB、单轮传输限制 16 MiB（含心跳）；超过限制中断接收并提示结果未确认，不静默截断。
- Next.js 可能把 Request.url 归一化为内部 localhost origin；浏览器同源校验以原始 Host 和协议为准，并且 Host 本身必须是回环地址。拒绝外部 Host，降低本机 DNS rebinding 风险；不信任 x-forwarded-host 作为公开入口。
- 浏览器响应与上游请求均禁用缓存；代理错误显式标为结果可能不明，不声称已取消。部署到有请求时限的平台前必须重新设计。
- Markdown 使用 react-markdown + GFM，跳过原始 HTML，外部图片改为说明文字以避免自动联网；工具输入输出用转义文本/JSON。外链使用安全 rel。

## 视觉与可读性
- 模型和思考强度使用输入框底部、发送按钮旁的紧凑原生下拉，保留键盘操作；厂商凭据配置入口放在左侧栏底部，不使用顶部横栏。切换中保留原生效值，错误/回退提示在输入区展示。
- 浅蓝色用于页面、卡片和装饰背景，不以淡蓝文字承载阅读内容；正文采用深蓝灰，操作采用明确的品牌蓝。
- 颜色集中在 `src/app/globals.css` 的语义变量中管理：正文、辅助文字、占位文字、操作色、边框及成功/警告/错误各有对应角色，避免散落近似浅色。
- 关键文字（包括占位说明、时间、警告及按钮标签）以至少 4.5:1 的对比度为目标。禁用态使用独立前景/背景，不以整体降低 opacity 使内容消失。
- 正文和输入采用 14px，辅助文字通常 12–13px，最小提示为 11px；窄屏不退回 8–9px 的小字。
- 阅读区域使用实色表面，使颜色组合和回归测试可预测；渐变仅用于无正文的装饰。短视口内容超出时从顶部可滚动，装饰图标不被挤扁。
- `tests/e2e/contrast.spec.ts` 检查桌面、窄屏、悬停、连接弹窗、禁用输入及消息/工具/非致命警告的实际计算颜色。它是关键场景回归，不等同于完整的无障碍认证。

## 测试策略
- Vitest：新增接口的路径/方法/请求体与运行时校验；SSE 单字节跨 UTF-8、半帧/多帧、未知事件/心跳、非法信封、递增序号及无终态断线；纯事件投影覆盖多助手、独立 reasoning、同名工具并行、各类工具结果和最终答案核对。控制器覆盖配置保存/启用分离、切换成功/拒绝/失败/回退、停止及会话隔离。
- React Testing Library + MSW：真实 API 客户端下的连接、创建、发送、历史替换、异常状态与安全渲染；在 Strict Mode 下验证页面初始化仅探测 runtime/目录、会话接入仍显式触发，且获取预览不会自动确认保存。
- 代理冒烟测试：实际构建的 Next.js + 随机端口本机 HTTP 替身，验证请求来源、编码 ID、配置 GET/POST/PUT、无认证访问、凭据过滤，以及响应在 EOF 前即交付 SSE、下游中止能关闭上游且无 POST 重试。测试进程结束后关闭服务。
- Playwright：使用路由 mock 的真实浏览器关键流程与窄屏布局，不连接真实后端。`feedback.spec.ts` 复现执行成功后列表刷新失败、关闭提示和只读检查；`scroll.spec.ts` 覆盖发送时恢复跟随，以及向上阅读后输出、完成、完整历史同步和普通弹窗更新不抢走阅读位置。浏览器可执行性依赖本机 Chromium 系统库；不能以 DOM/mock 测试替代实际浏览器通过声明。
- lint、tsc、Next build 是交付检查；启动和命令见 [README](../README.md)。

## 扩展方式
- 新增接口：先更新经过确认的契约文档，再增加 schema、OmtClient 方法及测试，随后接入对应功能。
- 新增功能：优先新增独立 feature，只依赖客户端公开 interface；确有复用再提取公共模块。
- 恢复认证：先确认新的后端契约、安全策略和部署边界，再设计凭据流程；当前不保留令牌输入、持久化或失效处理。
- SSE 与停止接收已按现有后端契约实现；未来的多用户、断线补发、后台运行查询、删除/编辑/重新生成等仍须先有后端契约，不能仅由 UI 模拟。

## 参考与取舍
- [Vercel Chatbot](https://github.com/vercel/chatbot)：参考页面与聊天布局，不引入其模型、数据库及认证体系。
- [assistant-ui](https://github.com/assistant-ui/assistant-ui)：参考组合式消息和工具展示，不直接接管其 runtime。
- [Next.js Route Handlers](https://nextjs.org/docs/app/getting-started/route-handlers)：同源代理采用 Node runtime。
- [Undici Dispatcher](https://github.com/nodejs/undici/blob/main/docs/docs/api/Dispatcher.md)：明确配置长请求超时。

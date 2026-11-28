# Token 消耗与上下文展示测试

本文中的后端命令在 `backend/` 目录执行；根目录命令见[开发说明](../../development.md)。接口字段的唯一来源是[前后端契约](../frontend-api.md#token-消耗与上下文快照)。

## 对象与目的

- 核心：[usage.py](../../../backend/src/omt/core/usage.py)、[conversation.py](../../../backend/src/omt/core/conversation.py)、[session_manager.py](../../../backend/src/omt/core/session_manager.py)。
- 接入与展示：[litellm_backend.py](../../../backend/src/omt/ai/litellm_backend.py)、[API](../../../backend/src/omt/api/streaming.py)、[CLI](../../../backend/src/omt/cli/terminal/tui.py)、[前端用量投影](../../../frontend/src/features/workspace/model/usage.ts)。
- 目的：累计消耗不能冒充上下文占用，纯工具请求不能漏计，缺失统计不能伪报精确零，初始化/恢复/切模型要正确对齐。

## 场景与可观察结果

| 场景 | 输入 / 前置条件 | 正确结果 | 测试 |
| --- | --- | --- | --- |
| 多次调用与多轮执行 | 假模型先仅请求本地工具，再回答，随后继续第二轮；参数化同步/异步 | 每次模型结束一次快照，累计为 120、350、690，最后占用为 340，不是累计 690；输入/输出分项正确 | `core/test_usage.py::test_conversation_reports_tool_only_call_and_cumulative_multiturn_usage` |
| 旧历史与非法用量 | 完整历史中最后一条 AI 消息缺失 usage；负数、缺键、布尔计数 | 累计只保留已知下界，最近占用/百分比/剩余为未知，不沿用旧请求；非法统计拒绝 | `core/test_usage.py::test_history_usage_missing_latest_call_is_unknown_not_zero_or_stale` |
| 初始化/切容量/超限 | 零历史、272000 容量、未知容量、占用超过容量 | `0 token 0%/272k`；未知不猜默认值；切容量不清累计；超限百分比可大于 100、剩余为 0 | `core/test_usage.py::test_initial_unknown_switch_and_overflow_windows_do_not_change_consumption` |
| 单位边界 | 0、100、999、1000、12500、999999、百万和十亿 | 整数或十进制 k/m/b，最多一位小数，临界舍入进位，两端规则一致 | `core/test_usage.py::test_compact_tokens_uses_decimal_units`、前端 `usage.test.ts` |
| SDK 容量解析 | 本地条目同时有输入/输出/旧 max_tokens；非法容量、其他厂商同名键、Ollama chat 路由 | 输入上限优先，不加输出上限；旧字段兼容；未知/错配不猜值；不联网 | `ai/test_model_capabilities.py` 的 `test_context_window_*` |
| 真实桥接的 usage-only chunk | 实际 ChatLiteLLM/LiteLLM，经 MockTransport 返回带空 choices 的最终用量块 | 请求启用 include_usage；同步/异步工具循环累计正确，恢复检查点后第三次调用不重复统计前两次 | `ai/test_litellm_stream.py::test_existing_conversation_interface_stream_tools_and_resume` |
| API 初始化、工具调用与重启 | TestClient + 真实 Runtime/Manager/SQLite，包含仅工具请求的模型调用 | GET runtime 零基线即有窗口，run.started 对齐历史，usage.updated 每次替换累计，终态相同；重启历史保留单次用量，下一轮从正确累计继续 | `api/test_runtime_streaming.py::test_usage_stream_aligns_initial_window_each_model_call_and_restart_history` |
| 未报告用量及模型切换 | 假模型不报告 usage；切到未知容量模型 | usage_complete=false，未知字段为 null，模型切换响应与下一次流立即更新容量 | `api/test_runtime_streaming.py::test_usage_unknown_model_missing_report_and_model_switch_are_explicit` |
| 执行失败 | 已报告 120 token 的工具请求随后工具抛异常 | run.failed 保留已知 120，但统计不完整、当前占用未知，不输出假成功或泄露异常 | `api/test_runtime_streaming.py::test_stream_rejections_and_sanitized_execution_failure` |
| 两种终端入口 | 假模型/真实 SQLite；参数化默认 TUI 与 plain | 输入下方初始 `0 token 0%/272k`，完成后 `27.2k token 10%/272k`；TUI 新建归零、恢复取原累计、小尺寸仍可见；plain 实际 PromptSession 底栏也更新 | `cli/test_tui.py::test_usage_below_input_initial_turn_restore_and_new_chat` |
| reasoning 兼容 | 原有分片模型不报告 usage | 原正文/reasoning 顺序不变，只在消息结束后增加 usage.updated，不重复内容 | `core/test_reasoning.py` |

## 前端验证

- [usage.test.ts](../../../frontend/src/features/workspace/model/usage.test.ts)：十进制缩写、初始容量、纯工具消息计数、旧历史下界、最新未知、超限、切模型重算、非法字段校验。
- [stream.test.ts](../../../frontend/src/lib/omt-api/stream.test.ts)：实际 SSE 解析保留开始/更新/终态快照，拒绝字符串形式的计数，不要求用量事件有消息 ID 或正文。
- [stream-state.test.ts](../../../frontend/src/features/workspace/model/stream-state.test.ts)：快照替换不累加、不生成聊天卡片，重复终态不重复统计；失败统计可保留已知下界。
- [controller.test.ts](../../../frontend/src/features/workspace/model/controller.test.ts)：流开始时对齐其他客户端更新后的容量，切会话后事件仍归原会话。
- [workspace.test.tsx](../../../frontend/src/features/workspace/workspace.test.tsx)：真实 API 客户端 + MSW，首次读取即显示容量，流在 EOF 前更新消耗，成功刷新历史不重复累计，新会话归零，切回旧会话及切模型重算正确。
- [workspace.spec.ts](../../../frontend/tests/e2e/workspace.spec.ts)：真实浏览器的输入框下方位置、流后更新及窄屏不溢出。需要可启动的 Chromium；环境缺系统库时不能宣称浏览器验证通过。

## 隔离

后端使用测试创建的假模型、本地工具、临时 SQLite、显式替换的 SDK 元数据和内存 HTTP 传输，不请求真实服务、不读取真实凭据。沿用各模块配置/Skills/MCP 隔离。CLI 通过 Textual Pilot 或 PromptSession 的 PipeInput/DummyOutput，不打开用户终端；原有 CLI fixture 返回可配置底栏的 Mock，而非 None。前端仅用 MSW、模拟客户端和浏览器路由 mock，不连接真实后端。

## 执行

```bash
uv run --frozen --no-sync pytest -q tests/core/test_usage.py tests/ai/test_model_capabilities.py tests/ai/test_litellm_stream.py tests/api/test_runtime_streaming.py tests/cli --tb=no
uv run --frozen --no-sync pytest -q --tb=no
# frontend 目录
npm run typecheck
npm test
npm run lint
npm run build
npm run test:proxy
npm run test:e2e
```

Python 修改文件另按开发说明执行 basedpyright。

## 覆盖限制

统计来自 SDK 暴露的 usage，并不保证提供商账单一致；没有 usage 时不自行估算费用。上下文取最近请求输入加输出，不是下一次发送前完整工具定义/新结果/草稿的预估，也不保证中转部署未缩小容量。断流/失败后已知消耗是下界，不是可恢复的独立账本；统计不另建数据库、不改变检查点及失败会话保护。真实模型、真实用户历史、跨进程并发和全部终端/浏览器渲染不属于离线测试通过的含义。

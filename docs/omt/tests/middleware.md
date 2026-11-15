# 工具 Middleware 测试说明

## 对象与目的

- 源码：[middlewares/](../../../backend/src/omt/core/middlewares/)、[middlewares_manager.py](../../../backend/src/omt/core/middlewares_manager.py)、[bootstrap.py](../../../backend/src/omt/core/bootstrap.py)。
- 测试：[test_middleware.py](../../../backend/tests/test_middleware.py)。
- 保证应用组装时安装统一工具错误保护：参数错误交回模型修正，工具执行异常按固定策略重试；不将取消、图暂停或内部 TypeError 误当作参数错误。

## 对外策略

`core.middlewares_manager.load_middlewares()` 每次返回新的 middleware 列表，当前唯一策略为继承预置 `ToolRetryMiddleware` 的 `ToolErrorMiddleware`。同步/异步重试循环和等待均使用 LangChain 实现，不另写重试循环。

- 首次调用后最多重试 3 次，即最多执行 4 次。`initial_delay=1` 秒、`backoff_factor=2`、`max_delay=8` 秒、`jitter=True`。
- 当前三次等待基准为 1、2、4 秒，预置 jitter 为 ±25%，实际范围依次为 0.75～1.25、1.5～2.5、3～5 秒。预置实现先限幅后抖动；当前三次重试不会触及 8 秒上限，不能据此认为修改重试次数后仍有同样的硬上限语义。
- 执行前按工具公开的 `args` 字段检查顶层未知参数名，避免默认 Pydantic schema 静默丢弃多余字段。未知参数直接返回修正提示，不执行工具、不重试，多个未知字段按名称排序；不修改原工具 schema。显式开放 `additionalProperties` 或使用组合/动态字段的 JSON schema 不做简单字段白名单推断。
- 其余 BaseTool 参数 schema 校验错误不重试，返回 `status=error` 和“工具参数错误：…请重新调用 tool”模板；保留字段位置和校验原因，不回显整份输入。
- 其他执行异常重试耗尽后返回 `status=error` 和“工具错误：异常类型: 原因”。不把所有 TypeError/ValueError 都归咎于模型参数。
- 本次调用复制工具的错误处理配置，不修改注册工具实例；关闭工具自身的 ToolException 转换，防止 MCP 适配器等提前把异常转成结果而绕过统一重试。
- 工具主动返回的普通结果或 ToolMessage 不触发异常重试；例如 Bash 的非零退出码仍作为工具结果交给模型判断。策略不根据返回正文猜测错误。

## 场景

| 场景 | 输入 / 前置条件 | 预期行为 | 对应测试 |
| --- | --- | --- | --- |
| 管理入口 | 连续加载 middleware | 独立实例，继承预置实现，参数与约定一致 | test_manager_returns_fresh_prebuilt_retry_policies |
| 正确参数 | 真实 read 传 file/offset/limit；真实 write 传 file/content | read 按指定偏移返回正文；write 实际覆盖临时文件；工具消息 name/id 正确、状态成功，无重试等待 | test_builtin_tools_accept_correct_arguments |
| 正确省略可选参数 | 真实 read 只传必填 file | 按默认 offset=1、limit=False 返回完整正文，不把省略可选参数误判为缺参 | test_builtin_read_accepts_omitted_optional_arguments |
| 参数过少 | 真实 read 缺 file、write 缺 content，以及两工具分别传空参数 | 返回参数错误、缺失字段名和 Field required，模型继续完成回答；不返回文件正文、不修改原文件、不等待重试 | test_builtin_tools_reject_insufficient_arguments |
| 参数过多 | 真实 read/write 均传齐全部合法参数，再多传 nonexistent_param | 返回 Extra inputs are not permitted 和重新调用提示；read 不返回正文、write 不覆盖文件，不等待重试 | test_builtin_tools_reject_excess_arguments_before_execution |
| 参数名不匹配 | 参数数量保持不变，把 read 的 file 写成 path，把 write 的 content 写成 text | 指出错误参数名，返回修正提示而不是成功使用默认值；文件不变、不等待重试 | test_builtin_tools_reject_mismatched_arguments 的 wrong-name 用例 |
| 参数类型不匹配 | 字段名和数量正确，但 read 的 offset 传非整数字符串，write 的 content 传字典 | 指出 offset/content 及所需类型，返回参数错误而不是工具执行错误；文件不变、不等待重试 | test_builtin_tools_reject_mismatched_arguments 的 wrong-type 用例 |
| 显式严格 schema 的参数错误 | 测试工具设置 extra=forbid，分别缺必填、错误类型、多传参数 | 工具体不执行，不等待、不重试；工具消息保留 name/id；注册工具配置不变，模型继续完成回答 | test_argument_errors_return_correction_template_without_retry |
| 默认 schema 的未知参数 | 普通 @tool 未配置 extra=forbid，传入两个额外字段 | 工具体不执行，按字段名排序返回修正提示，不泄露额外字段的输入值 | test_default_schema_rejects_extra_arguments_without_executing_tool |
| JSON schema 字段契约 | MCP 风格本地字典 schema，additionalProperties 分别为 false/true | 封闭字段工具拒绝多传字段；明确开放动态字段的工具正常收到并处理这些字段，无异常重试 | test_json_schema_extra_field_policy_is_respected |
| 工具持续失败 | RuntimeError、内部 TypeError、ToolException，且工具自身启用了异常处理 | 同步/异步均执行 4 次后返回工具错误；不误报参数错误，不修改原工具错误配置 | test_tool_errors_retry_three_times_with_exponential_jitter_then_return_error |
| 指数退避和抖动 | 将随机数固定为抖动上下界 | 记录到的三次等待分别为基准值的 75% 或 125%，均不超过 8 秒 | 同上 |
| 正常及重试成功 | 首次成功，或失败 2/3 次后成功；工具有注入的 ToolRuntime | 成功立即停止，不改变正常结果；注入的调用 ID 可用 | test_success_stops_retry_and_preserves_injected_runtime |
| 纯异步工具 | async 工具首次 OSError 后恢复 | 使用异步等待，第二次成功，不走同步 sleep | test_async_only_tool_recovers_after_retry |
| 工具内取消 | async 工具抛 CancelledError | 不重试、不转成 ToolMessage；LangGraph 在图边界以 NodeCancelledError 保留取消原因 | test_async_tool_and_cancellation_are_not_swallowed |
| 图控制信号 | 工具调用 interrupt | 暂停信号向上传播，无重试或伪造工具结果 | test_graph_interrupt_is_not_retried |
| 应用集成 | build_agent 接收假模型和额外工具，请求缺参 | 无需调用方手动传 middleware，就能返回参数修正模板并完成模型循环 | test_bootstrap_installs_error_policy_for_extra_tools |

## 隔离方式

上述四类参数契约全部通过真实 Agent 图和真实注册的 read/write 工具验证，各自覆盖同步 invoke 与异步 ainvoke；不只调用格式化函数，也不依赖测试专用的严格 schema。除状态和提示外，还检查实际读取结果、文件内容是否发生预期变化、工具调用关联和最终模型回答。

使用预置 middleware 和本地 FakeMessagesListChatModel。读写工具仅操作 tmp_path 下的测试文件，其他工具仅操作测试内存，不请求网络、不读取用户配置、不启动 MCP，不执行真实 Bash 或写入用户文件。仅替换预置重试模块引用的等待对象，不替换全局 asyncio/time；抖动测试固定随机上下界，避免不稳定断言。

## 执行

从仓库根目录执行：

```bash
# 单独验证正确、缺少、多余、名称/类型不匹配及省略可选参数
uv run --frozen --no-sync --project backend pytest -q backend/tests/test_middleware.py -k 'builtin_tools or builtin_read' --tb=no
uv run --frozen --no-sync --project backend pytest -q backend/tests/test_middleware.py backend/tests/core/test_bootstrap.py --tb=no
uv run --frozen --no-sync --project backend pytest -q backend/tests --tb=no
cd backend && basedpyright src/omt/core/middlewares src/omt/core/middlewares_manager.py src/omt/core/bootstrap.py tests/test_middleware.py
```

## 覆盖限制

- 不验证真实模型是否遵循修正提示，也不验证远程工具恢复能力或真实网络耗时。
- 未启动真实 MCP；带预设 ToolException 处理器的本地工具用于验证防止异常被提前吞掉的策略。
- 未知字段检查只覆盖调用参数的顶层字段，不是完整 JSON Schema 校验；显式开放额外字段或使用 patternProperties/$ref/allOf/anyOf/oneOf 等动态、组合契约的 JSON schema 交给后续执行链处理。嵌套字段、类型和值仍依赖 BaseTool 的 schema 校验机制，不靠异常文本推断任意工具内部的 TypeError 是参数错误。
- 不提供幂等保证、权限审批、沙箱或副作用回滚；工具可能在报错前已经部分执行，自动重试可能重复副作用。

# LiteLLM Ollama 路由测试说明

本文中的命令在仓库 `backend/` 目录执行；根目录命令见 [开发说明](../../development.md)。

## 对象与目的

- 源码：[litellm_backend.py](../../../backend/src/omt/ai/litellm_backend.py)、[models_manager.py](../../../backend/src/omt/ai/models_manager.py)。
- 测试：[test_ollama.py](../../../backend/tests/ai/test_ollama.py)、[test_models_manager.py](../../../backend/tests/ai/test_models_manager.py)、[test_model_catalog.py](../../../backend/tests/ai/test_model_catalog.py)。
- 目标：上层仍使用 provider=ollama 和原有免 Key 配置，底层统一走 ChatLiteLLM/LiteLLM 的 ollama_chat 原生聊天路由，不再依赖 ChatOllama、ollama_init 或 OMT 自写目录请求。

## 场景

| 场景 | 输入 / 前置条件 | 预期结果 | 对应测试 |
| --- | --- | --- | --- |
| 同步/异步实际 SDK 协议 | qwen3:8b、原有 HttpUrl 默认地址、兼容假 Key、effort=none；测试显式声明 SDK none 等级，真实 LiteLLM 配内存 HTTP | 构造不发请求；invoke/ainvoke 发往 /api/chat，不产生双斜杠、不转 OpenAI /v1；模型标签保留，SDK 转换 think=false；不发送旧 Key | test_litellm_native_ollama_request_and_reasoning |
| 返回正文与思考 | 内存响应的 message 含 content/thinking，带计数 | AIMessage 正文与 reasoning_content 分离，保留现有上层读取方式 | 同上 |
| 共用选项与免 Key | 旧占位 Key、num_ctx、effort=none | Key 被注册入口丢弃；其他选项交给 SDK，输入字典不变 | test_ollama_discards_compatibility_key_and_does_not_mutate_options |
| SDK 目录 | 注册入口省略 Key；SDK 返回带 ollama/ 前缀及 :tag 的 ID | 交给 get_valid_models，返回去前缀、去重排序的名称；不再补发本地 HTTP | test_catalog_uses_litellm_and_preserves_raw_ids 的 ollama 参数项 |

旧用例中 OMT 自行将 true/false/low/medium/high 转成 ChatOllama.reasoning、拒绝 max、限制目录 HTTP 的断言已移除。现在 effort、num_ctx/num_predict 等参数解释由 LiteLLM 承担；不能把旧原生 SDK 的全部专有参数视为等价支持。安装版本对一般 Ollama 模型的 low/medium/high 会转换为布尔 think，对部分模型另有规则，OMT 不再维护厂商协议分支。

## 上层回归

core/CLI/TUI/HTTP 首次配置、取消、保存、不写 auth、切换及重启仍由 [模型登录测试](model-login.md)、[TUI 测试](tui.md)、[HTTP 运行配置测试](api-runtime-streaming.md) 和 [组装测试](session-and-config.md) 验证。`requires_api_key=False`、`logged_in=False` 的语义与配置 DTO、JSON 字段没有变化。

## 隔离方式

使用实际安装的 SDK 与 HTTPHandler/AsyncHTTPHandler，传输为 httpx.MockTransport；无服务进程、模型文件、推理调用或用户数据库。测试结束关闭客户端；自动 fixture 阻断 DNS 和 socket.connect，避免客户端接缝不匹配时联网。上层配置测试继续隔离临时目录、环境变量、Skills 和 MCP。

## 执行

```bash
uv run pytest -q tests/ai/test_ollama.py tests/ai/test_models_manager.py tests/ai/test_model_catalog.py --tb=no
uv run pytest -q tests/core/test_bootstrap.py tests/cli/test_login.py tests/cli/test_tui.py tests/api/test_runtime_streaming.py --tb=no
```

## 覆盖限制

- 不证明本机已安装/启动 Ollama、下载模型、GPU 性能或某模型支持工具/思考。
- 目录由 LiteLLM 决定是否联网及静态回退。空/异常结果仍可让上层安全报错或使用 OMT 已保存目录，但 SDK 非空静态结果不能证明服务已启动或模型已下载。
- 不实现 Ollama 云端认证、自动识别 /v1 地址或自动修复用户配置；不保证旧目录 HTTP 的超时、限额和重定向约束。

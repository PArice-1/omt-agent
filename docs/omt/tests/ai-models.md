# 统一模型底座测试说明

本文中的命令在仓库 `backend/` 目录执行；根目录命令见 [开发说明](../../development.md)。

## 对象与目的

源码：[model.py](../../../backend/src/omt/ai/model.py)、[models_manager.py](../../../backend/src/omt/ai/models_manager.py)、[litellm_backend.py](../../../backend/src/omt/ai/litellm_backend.py)。

保证上层仍使用 `Model(provider, model=..., base_url=..., **kwargs).model`、`ModelProvider`、`models_provider` 和 `list_provider_models`。只有底座改为 ChatLiteLLM + LiteLLM；原生 DeepSeek/Ollama SDK 与 OMT 自写 HTTP 查询已移除，没有后端切换开关或原生回退。Agent、Conversation、配置 DTO、JSON 和 HTTP/SSE 字段不改。

原 test_deepseek.py 中针对旧 SDK 的参数/HTTP 断言已由统一层与真实 LiteLLM 离线协议用例替代，不能继续要求 OMT 构造旧 extra_body。

## 初始化与协议场景

| 场景 | 输入 / 前置条件 | 预期结果 | 测试文件 / 函数 |
| --- | --- | --- | --- |
| 全部开放厂商 | 注册表每个 provider、含斜杠与标签的模型 ID、假凭据、temperature | 同一个 ChatLiteLLM 工厂；保留 ID，显式路由、地址、Key 与选项；返回可调用模型；Ollama 路由为 ollama_chat | test_ai.py：test_all_providers_use_common_litellm_bridge |
| 上层默认 none | 参数能力表声称支持 reasoning_effort，但具体 SDK 等级不声明 none；另测 high | 不发送未知关闭值；high 不静默丢弃，交 SDK 校验；不能仅根据参数名支持就推断支持 none | test_ai.py：test_shared_none_contract_does_not_break_non_reasoning_models |
| 构造失败 | 工厂抛假异常 | 原异常传播，不保存字符串或伪模型 | test_ai.py：test_constructor_does_not_return_a_model_on_failure |
| 注册与认证 | 未登记厂商、空/非法 Key、空白模型名 | SDK 构造前失败；注册范围可扩展，但不代表 LiteLLM 的全部认证方式都已接入 | test_models_manager.py 的 registry、unknown、cloud、blank 用例 |
| 运行时类型校验 | provider/model 非字符串、FTP 地址、错误 Key/effort 类型 | 注册回调拒绝，不初始化 SDK | test_models_manager.py：test_registered_initializer_validates_types_before_sdk |
| 免 Key 与参数副作用 | Ollama 输入旧假 Key、none、num_ctx | 不向底座传旧 Key，保留其他选项，原字典不变 | test_models_manager.py：test_ollama_discards_compatibility_key_and_does_not_mutate_options |
| DeepSeek 同步/异步协议 | 测试元数据显式声明 none/high；真实 SDK、MockTransport 与代理前缀 | none/high 分别转换 disabled/enabled；保留路径、正文、reasoning 和 usage；不声称 SDK 包内已给 DeepSeek 完整档位 | test_litellm_backend.py：test_deepseek_uses_litellm_translation_and_preserves_reasoning |
| SDK 认证失败 | MockTransport 返回 HTTP 401 | 同步/异步继续传播 AuthenticationError，不返回假答案，不重复请求 | test_litellm_backend.py：test_sdk_authentication_failure_propagates_without_fake_answer |
| 原有上层流与工具循环 | 真实 Model → Agent → Conversation；SSE 返回 reasoning 与分片工具参数 | 同步/异步都只执行一次工具，结果带原调用 ID 回传；正文/reasoning 事件不重复、不混入答案；检查点恢复后保留完整历史 | test_litellm_stream.py：test_existing_conversation_interface_stream_tools_and_resume |

Ollama 同步/异步协议专项见 [Ollama 测试](ollama.md)。SDK 能力的登录、组装和运行切换见 [组装测试](session-and-config.md)、[登录测试](model-login.md)、[推理测试](thinking.md)。这些测试仅注入 SDK 元数据，不再通过本地目录映射指定能力。

## SDK 本地思考能力

同一元数据源也提供上下文容量；容量字段优先级/非法值/跨厂商隔离与真实桥接 usage-only chunk 的累计、恢复统计，见[Token 用量专项](usage.md)。

[test_model_capabilities.py](../../../backend/tests/ai/test_model_capabilities.py) 使用真实固定版本的数据验证 gpt-5 的 minimal/low/medium/high，以及 gpt-5.1 的 none/low/medium/high；同时用临时 model_cost 条目验证多厂商、非连续档位不补 medium、未知与明确不支持分离、裸模型名不跨厂商串用。所有路径被 ai 的 DNS/socket 防护约束，不调用 get_model_info 或 Ollama /api/show。

SDK 等级解析依赖内部 resolve_supported_reasoning_efforts，升级依赖须重跑此专项。上层测试显式申请根 tests/conftest.py 的 sdk_reasoning fixture，只替换测试模型元数据，非 autouse，不污染真实 SDK 专项。none 是应用回退项，只有 SDK 明确声明才作为关闭参数发送。

## 厂商模型目录查询

[test_model_catalog.py](../../../backend/tests/ai/test_model_catalog.py) 经公开 `list_provider_models` 调用 `litellm.get_valid_models(check_provider_endpoint=True, ...)`。仅按所选 provider 查询，传可信默认地址和适用凭据，不再补发 OMT 的 /models 或 /api/tags 请求。

| 场景 | 输入 / 前置条件 | 预期结果 | 对应测试 |
| --- | --- | --- | --- |
| 全部厂商走 SDK | 每个注册项；SDK 返回带 provider 前缀、重复、空白与多层斜杠的 ID | 指定 provider/地址/Key，去掉匹配的一个前缀，保留其余 ID 和标签；去空、去重、排序 | test_catalog_uses_litellm_and_preserves_raw_ids |
| 空目录/失败 | 空列表、仅空白或前缀、SDK 异常带假敏感标记 | 安全 ValueError，不泄露原异常，不伪造模型 | test_empty_or_failed_catalog_is_a_safe_error |
| 连接校验 | 未知厂商、需认证厂商无 Key | 调用 SDK 前拒绝 | test_catalog_rejects_invalid_connection_before_sdk |
| SDK 内置目录 | SDK 直接返回 DeepSeek 内置 ID | 直接采用，不补写官网 HTTP 请求；非空不能解释成 Key 已验证 | test_static_catalog_does_not_trigger_extra_official_request |

**目录来源的限制：**`check_provider_endpoint=True` 不等于每家都会联网。安装版本的 DeepSeek 可返回包内目录，Ollama 等也可能在 SDK 内部回退。上层 `from_cache` 只表示 OMT 自己复用保存的目录，不表示 SDK 结果必为实时。旧查询的十秒超时、1 MiB 限额与禁止重定向不再由 OMT 保证。

## 隔离方式

- `ai/conftest.py` 的工厂 fixture 返回 FakeListChatModel，保留真实 Model/注册表/共用初始化链。目录测试仅替换 SDK 目录入口。
- 协议测试使用实际安装的 ChatLiteLLM、LiteLLM，通过其 HTTPHandler/AsyncHTTPHandler 注入 httpx.MockTransport；同步和异步均关闭测试客户端，不连接任何服务。
- ai 测试自动阻断 DNS 解析与 socket.connect，防止 SDK 客户端接缝升级后意外联网。Key 全为假值，不读取用户配置、不调用真实模型。
- 流测试工具只操作内存，Skills 显式禁用，检查点使用 InMemorySaver；不写用户文件或数据库。
- LiteLLM 默认使用包内能力/价格表，避免导入时下载远程表；用户显式环境配置不覆盖。

## 执行

```bash
uv run pytest -q tests/ai --tb=no
uv run pytest -q tests/core/test_bootstrap.py tests/core/test_reasoning.py tests/cli/test_login.py tests/cli/test_thinking.py tests/api/test_runtime_streaming.py --tb=no
uv run pytest -q --tb=no
basedpyright src/omt/ai/model.py src/omt/ai/models_manager.py src/omt/ai/litellm_backend.py tests/ai
```

## 覆盖限制

- 不证明真实服务可达、Key 有效、返回的每个 ID 都能聊天/调用工具，或厂商接受任意 effort；不验证费用、质量、性能、速率限制和真实中断。
- 十个注册项都验证共用参数路由；真实 SDK 的内存线协议主要验证 DeepSeek/Ollama，不能据此声称全部厂商已联调。
- SDK 负责厂商协议、目录 HTTP 与内部缓存/回退；OMT 不重新实现这些逻辑。升级依赖后须重跑协议与上层回归。
- langchain-litellm 固定兼容版本、LiteLLM 限定小版本；更新前需同时检查 MCP 依赖与 v3 流。上层配置/会话接口稳定不代表原生 SDK 专有选项均与新底座等价。

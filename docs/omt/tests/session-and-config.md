# 模型配置与共用组装测试说明

本文中的模块级命令在仓库的 `backend/` 目录执行；根目录命令见 [开发说明](../../development.md).

## 对象与目的

- 源码：[settings.py](../../../backend/src/omt/core/settings.py)、[bootstrap.py](../../../backend/src/omt/core/bootstrap.py)。
- 测试：[test_settings.py](../../../backend/tests/core/test_settings.py)、[test_configuration_files.py](../../../backend/tests/core/test_configuration_files.py)、[test_bootstrap.py](../../../backend/tests/core/test_bootstrap.py)。
- 防止选错模型或 URL、将 OAuth 当 Key、配置报错泄露凭据，以及测试误读用户配置。

原 test_session.py 的模型解析和 Agent 组装用例迁入 test_bootstrap.py，直接测试共用 build_model/build_agent，不再经已删除的 CLI 私有别名。交互、输入、信号与完整组装链路迁入 [CLI 测试](cli.md)，恢复迁入 [/resume 测试](resume.md)。这不是删除旧行为覆盖：低层模型断言保留；旧失败后直接重试契约按 Manager 的保守策略替换。

配置读取器保持严格只读，直接调用缺失文件仍报错；免 Key 的 Ollama 构建不会调用 auth 读取器，因此不要求该文件存在。显式登录由 core/model_configuration.py 校验并持久化，不再放在 CLI；就绪检查允许缺默认字段并返回未就绪，让 CLI 提示 /login。数据库初始化另由 core/store.py 的显式函数承担，见[模型登录测试](model-login.md)，不在读取器中添加隐式写入。

## 配置读取场景

| 场景 | 输入 / 前置条件 | 预期结果 | 对应测试 |
| --- | --- | --- | --- |
| Settings 字段 | 合法 provider/model，或缺字段、错误类型、空白值 | 合法值可加载，缺失/非法选择被拒绝 | test_settings.py 的 accepts/reject 用例；test_configuration_files.py：test_settings_reject_blank_selection |
| 可选思考等级 | settings.json 不提供 defaultThinkingLevel，或提供 null/media/high/none/custom | 未配置和 null 读取为 None，组装时按 none 处理；非空显式等级可读取，空白/错误类型拒绝 | test_settings.py：test_settings_accept_valid_values、test_load_settings_reads_thinking_level、test_settings_reject_invalid_thinking_level |
| 文件与缓存 | 临时 settings.json、文件缺失、错误 JSON、修复后重试、成功后修改文件 | 错误传播；成功结果缓存，cache_clear 后读取新值；失败不固化为缓存结果 | test_settings.py 的 load/missing/invalid/cached/retried 用例 |
| API Key 类型 | auth 中提供假 Key | 加载为 SecretStr，可明确取测试值，但 repr 不暴露原值 | test_auth_loads_api_key_as_masked_secret |
| 非 API Key 认证 | OAuth 类型附带 access/refresh | 加载类型，不误用为 key；额外 token 不显示在对象 repr | test_auth_retains_type_without_treating_oauth_as_api_key |
| 非法认证结构 | 尾随逗号、缺 type、错误结构，携带测试敏感标记 | 带文件提示的错误；完整格式化异常也不含该标记 | test_invalid_auth_errors_do_not_expose_credentials |
| 认证重读 | 假 Key 改变，或 auth 文件不存在 | 下次读取新值；缺文件抛异常 | test_auth_is_reread_after_credentials_change、test_missing_auth_file_raises |
| 目录字段 | 模型带 URL、provider 及能力/价格额外字段 | 连接字段可用，额外元数据不妨碍加载 | test_model_store_parses_model_url_and_ignores_catalog_metadata |
| 废弃思考字段 | 目录保留任意旧 thinkingLevelMap 值 | 一律不参与模型定义/能力解析；仅读取时保持文件字节不变，不再因旧映射结构错误拒绝连接 | test_configuration_files.py：test_model_store_parses_model_url_and_ignores_catalog_metadata、test_model_store_ignores_obsolete_thinking_mapping |
| 非法目录 | 错误 JSON、错误顶层、缺 URL、非 HTTP(S) URL、空 ID、重复 ID、缺文件 | 拒绝目录或报文件缺失，不选择一个凑合使用 | test_invalid_model_store_is_rejected、test_missing_model_store_file_raises |

## 共用模型与 Agent 组装

| 场景 | 输入 / 前置条件 | 预期结果 | 对应测试 |
| --- | --- | --- | --- |
| Ollama 无认证文件构建 | 临时目录仅有模型定义，删除 auth.json；选择 Ollama，SDK 工厂返回 FakeListChatModel | build_model 经真实 Model/注册表适配返回可用模型，不读取或新建 auth；统一底座收到 reasoning_effort=none，不传 api_key；旧 DeepSeek 缺 Key/OAuth 拒绝回归保留 | test_get_ollama_model_without_auth_file |
| 三份配置拼接 | 假默认选择、认证与目录匹配，省略 defaultThinkingLevel，目录仍有 media→high | provider/model/精确 URL/SecretStr 传至 SDK 替身，不因目录存在映射就默认开启 thinking，向统一底座传 effort=none，返回可用模型 | test_get_model_joins_settings_auth_and_matching_catalog_entry |
| 显式思考等级 | SDK 声明 low/high/max，磁盘故意保留 high→max | high 直接透传 high，旧转换不生效；none 不会被旧表重新开启 | test_get_model_uses_sdk_level_and_ignores_legacy_mapping |
| 未配置或 SDK 等级不可用 | None/media/none 等请求，磁盘保留多种废弃映射形态 | 回退 none，模型可用；不由组装层拼厂商协议 | test_get_model_uses_none_when_thinking_is_unconfigured_or_unavailable |
| 认证不可用 | provider 无认证、Key 缺失/空白、OAuth/bearer/未知类型 | 初始化前报错，SDK 替身未调用；错误不含测试 token | test_get_model_rejects_missing_or_blank_auth、test_get_model_explicitly_rejects_unsupported_auth_types |
| 提供商与目录不匹配 | provider 未注册、目录缺 provider/model、模型 provider 不符 | 明确拒绝，不回退到其他模型 | test_get_model_rejects_unregistered_provider_before_initializing_model、test_get_model_rejects_missing_or_mismatched_catalog |
| 精确 URL 选择 | 所选 ID 不是目录首项 | 只使用精确 ID 的 URL 和 SDK 能力，不要求其他模型已知能力 | test_get_model_uses_url_of_exact_selected_model_not_first_entry |
| 目录快照匹配 | 显式传入 definition，ID 或 provider 与设置不同 | 初始化前拒绝，SDK 不调用；不能为保持展示快照而绕过模型选择约束 | test_get_model_rejects_mismatched_definition_snapshot |
| 隔离模型快照 | 显式 definition/credentials，删除配置；空认证与本次 effort 覆盖 | 复用连接/认证快照、SDK 能力，不读用户文件；空认证不回退文件，覆盖值不持久化 | test_build_model_from_explicit_snapshot_does_not_read_configuration_files、test_explicit_empty_credentials_do_not_fall_back_to_saved_auth |
| 只读模型预检 | 合法三份临时配置，SDK 工厂为替身 | resolve_model_parameters 返回受 SecretStr 保护的参数，不构造客户端、不发送模型请求 | test_resolve_model_parameters_checks_auth_without_constructing_client |
| Agent 组装 | Model 包装对象与内置工具，MCP 发现返回空列表的异步替身 | 等待异步 build_agent，传入 client.model，工具集合包含全部静态注册项 | test_get_agent_uses_underlying_chat_model_and_builtin_tools |

需求调整：目录和能力分离，旧 high→max 等本地映射全部失效。测试用 SDK 元数据替身声明有效等级；未知能力仅回退 none，不阻断模型。连接、认证、JSON 语法错误的严格校验保持不变。手动导入但 SDK 未收录的模型通过真实 build_model→Model 链和本地 FakeListChatModel 调用验证，见 test_off_catalog_model_remains_callable_without_sdk_capability_metadata。

上述 test_bootstrap.py 用例沿用原 test_get_model/test_get_agent 名称，仅被测函数改为共用 bootstrap 实现。固定模型的 open_session_manager 和 CLI/HTTP 默认使用的可切换 open_session_runtime 的实际创建/关闭、预建库校验和提示词传递由 [CLI](cli.md)、[推理强度](thinking.md)与 [HTTP](api.md) 集成测试验证；共用启动选项 SessionSettings 的路径/MCP 校验主要在 HTTP 配置与 CLI 配置用例中覆盖。

## 隔离方式

[core/conftest.py](../../../backend/tests/core/conftest.py) 同时隔离 settings.root 与 cwd，前后清空 load_settings 缓存。所有 JSON 均写在 tmp_path，使用保留域名与假 Key，不输出真实认证文件。

模型组装只替换共用 initialize_litellm_model 端点，保留从 build_model → Model → 注册入口的调用链；返回 FakeListChatModel，不发网络请求。Agent 用真实内置工具定义，默认不传 MCP 配置，不启动 MCP。配置解析错误仅包含测试假标记，用于检验完整格式化异常也不泄密。

不能只切换 cwd：settings.root 在模块导入时就已固定；新增配置测试必须使用共享 fixture 或显式隔离该值并清缓存。

## 执行

```bash
uv run pytest -q tests/core/test_settings.py tests/core/test_configuration_files.py tests/core/test_bootstrap.py --tb=no
uv run pytest -q tests/cli tests/api --tb=no
basedpyright --pythonpath .venv/bin/python src/omt/core/bootstrap.py src/omt/core/configuration.py tests/core/test_bootstrap.py
```

## 覆盖限制

- 不读取或验证用户现有配置，不请求真实模型、OAuth、MCP 或代理。
- SDK 替身验证连接参数，不证明真实服务可达或凭据有效。
- 不验证多进程共享设置缓存或热重载；成功配置缓存需调用方主动清理。
- 不把输入校验、目录 resolve 或提示词当成权限和沙箱实现。

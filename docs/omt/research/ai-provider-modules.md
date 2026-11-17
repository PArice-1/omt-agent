# 可独立复用的开源 Agent 模型层调研

调研日期：2026-11-16。目标：为 OMT 寻找持续维护、相对成熟、模块划分清晰的开源项目，重点判断其 **AI / 多模型接入层能否单独复用或修改**，不是选一个完整 Agent 替换 OMT。

本文保留迁移前的选型研究快照。结论来自官方仓库、官方文档源码、包清单及 GitHub 提交/发布记录；研究阶段未安装候选依赖、未调用真实模型、未做性能或兼容性实测。

**后续实验状态：**按用户后续“调用和目录全部换成 LiteLLM，不保留本地厂商接口；上层接口不变”的要求，当前分支已实施统一底座，明确接受下述静态目录/回退局限。使用兼容版本的 ChatLiteLLM/LiteLLM，不设原生回退开关。具体实现和离线验证以[当前架构](../architecture.md#3-模型连接与配置)和[统一模型测试](../tests/ai-models.md)为准；本文第二节的注册范围和第十节的原生查询链描述的是实验前基线，不代表当前源码。

## 一、结论先行

> **进一步核验：实时模型发现也是硬要求时，LiteLLM 不能视为现有 AI 模块的完整即插即用替代。** 它有统一发现入口，但部分 provider 仍返回内置目录；例如本次核验的 DeepSeek 实现不请求官方模型列表。应将下面的“首选”限定为模型调用底座候选，完整替换结论以第十节为准。

**按用户补充的硬要求——“模块内已经实现大部分厂商接口，接入一次即可切换，不再逐个写厂商适配，并允许删减”——Python OMT 的首选应是 LiteLLM，而不是逐个扩展 LangChain 集成。** 初版将“保持现有框架、最小改造”排在前面，没有充分满足“不想逐个接入”的目标，本版据此修正。

具体建议：

1. **保持 Python、优先现成覆盖：LiteLLM SDK。** 它已实现大量厂商适配，统一调用时主要更换 provider/model 标识和配置；通过现成的 `langchain-litellm` 接回当前 Agent，无须自己逐个写 OpenAI、Anthropic、Gemini 等协议。LiteLLM 不是 Agent，但正是 OpenHands 等 Agent 使用的模型底座。[LT1][OH2][LB1]
2. **保持 Python、优先清楚的源码分工和可选依赖：PydanticAI。** 它的 `models / providers / profiles` 和 `direct` 接口也已实现多厂商支持；按需安装 extras 不等于自己实现厂商。只是接回当前 LangChain 执行层仍需统一 Adapter。[PA1][PA2][PA3]
3. **接受 TypeScript、希望 AI 层本来就是独立包：Pi AI。** 不必复制整个编码 Agent，现成处理模型、流、工具调用、推理、认证与历史转换。[PI1][PI2]
4. **另一个 TS 拆包参考：OpenCode 当前开发分支。** 已有 `@opencode/ai`，但要考虑 Effect、工作区依赖及尚未核实的 npm 发布状态。[OC1][OC2]
5. **OpenHands、smolagents 主要作为使用现成模型底座的参考，Goose 作为 Rust 路线参考。** 不必为了取得 LiteLLM 的模型覆盖，再把整套 Agent 模型包装搬进来。[OH2][SM1][GO1]

这里有两种不同的“删减”：**配置白名单/不安装可选依赖**，与**物理删除源码和依赖**。前者适合先落地；后者需要同步清理注册、导入和测试，任何候选都不能承诺随意删除目录仍正常工作。LiteLLM 的现成覆盖强，但不应因此把它描述成最容易物理裁剪的实现。

**不建议因为注册了两个厂商，就直接重写整个 Agent、会话和检查点系统。你的问题目前主要在模型接入范围，不是缺少 Agent 框架。**

## 二、你当前项目真正受限在哪里

根据本地源码，而非仅凭项目描述：

- [`backend/src/omt/ai/models_manager.py`](../../../backend/src/omt/ai/models_manager.py) 的 `models` 注册表只有 `deepseek`、`ollama`。
- 你已经将厂商初始化、模型目录查询、默认地址、是否需要 Key、思考等级映射收口到 `ModelProvider`，**具备可替换的接缝，不是从零开始的混杂实现**。
- [`ai/model.py`](../../../backend/src/omt/ai/model.py) 最终返回厂商创建的聊天模型；[`agent/agent.py`](../../../backend/src/omt/agent/agent.py) 使用 LangChain `create_agent`，接收 `str | BaseChatModel`。
- [`backend/pyproject.toml`](../../../backend/pyproject.toml) 已依赖 LangChain/LangGraph，并单独安装 DeepSeek、Ollama 的集成包。
- 配置、会话、工具循环和事件投影已分层，详情见[当前架构](../architecture.md)。换模型层时，不应顺便搬走 `SessionManager`、SQLite 检查点或 CLI/API。

因此，“支持模型少”至少有四种不同情况，应分别解决：

| 层次 | 需要的能力 | 不能混为一谈的事情 |
| --- | --- | --- |
| 模型调用 | 接入 OpenAI、Anthropic、Gemini、Bedrock 等协议 | 在列表里加模型名称，不等于实现对应协议 |
| 模型目录 | 展示模型 ID、上下文、工具/视觉/推理能力、价格 | 静态目录不等于当前账号能调用；并非每个厂商都提供完整目录接口 |
| 认证 | Key、无 Key、本机凭据、云身份、OAuth 刷新 | 支持 API Key，不代表支持订阅账号登录 |
| 历史与事件 | 消息转换、工具 ID、推理签名、流式增量、usage、取消 | 第一轮能回答，不代表多轮工具执行和跨模型切换正确 |

本报告优先评价后面这些真实集成成本，不按宣传中的模型数量排序。

## 三、候选总表

以下“可拆程度”和“成本”是基于源码结构的工程判断，不是实际移植结果。成本指接入当前 **Python + LangChain/LangGraph** 的 OMT。

| 项目 | 类型 / 语言 | 开源许可证 | 真正可复用的范围 | 拆分情况 | OMT 接入成本 | 建议 |
| --- | --- | --- | --- | --- | --- | --- |
| **LiteLLM SDK** | 多厂商模型库，非 Agent / Python | 核心 MIT，enterprise 另许可 | 统一 completion/Responses 调用与现成 provider 实现 | 可直接作为库使用；覆盖广但有集中导入/路由，物理裁剪需处理依赖 | 较低至中：可用现成 LangChain 集成，仍须契约验证 | **不逐厂商写适配的首选** |
| **PydanticAI** | Agent 框架 / Python | MIT | `direct`、`models`、`providers`、`profiles`、消息类型 | 有公开低层接口；模型层未单独成为纯模型发行包 | 中：需 LangChain Adapter | **重视源码分工与可选依赖时的 Python 候选** |
| **Pi** | 编码 Agent + 工具包 / TypeScript | MIT | `packages/ai` → `@earendil-works/pi-ai` | 明确的独立包；依赖少量同仓公共包及厂商 SDK | 中高：跨语言桥接，或较大移植 | **最符合“像 Pi 一样拆 AI 层”的基准** |
| **OpenCode** | 编码 Agent / TypeScript、Effect | MIT | 当前开发分支 `packages/ai` → `@opencode/ai` | 明确包与公开入口；含工作区依赖 | 中高：跨语言、Effect、版本选择 | **值得研究的第二套 TS 方案** |
| **OpenHands Software Agent SDK** | 编码 Agent SDK / Python | MIT | `openhands.sdk.llm` | SDK 内清楚分目录；不是独立 LLM 包 | 中高：SDK 耦合 + LangChain Adapter | **借鉴编码场景策略，多模型底座可直接看 LiteLLM** |
| **Goose** | 编码/通用 Agent / Rust | Apache-2.0 | `goose-provider-types`、`goose-providers` | 当前已独立 crate；实现 crate 为 alpha 版本 | 高：Rust 桥接或重写 | **Rust 方向好参考，当前 OMT 不优先** |
| **smolagents** | 轻量 Agent 框架 / Python | Apache-2.0 | `src/smolagents/models.py` 及其消息、工具、辅助依赖 | 代码易定位，但不是独立模型包 | 中：要处理内部依赖和 LangChain 转换 | **适合学习/小规模二次开发，不是最完整底座** |
| **LangChain / LangGraph 生态** | Agent 框架 / Python | LangChain 仓库 MIT；外部集成另核许可证 | `BaseChatModel`、`init_chat_model`、各厂商集成包 | 核心抽象与各厂商包分开 | 原生路径需逐项安装/配置；LiteLLM 路径可共用一个集成 | **保留执行层，不再把逐厂商扩展作为首选** |

许可证依据对应仓库和包清单；重分发仍需保留适用的版权、许可证与 NOTICE 等文件，不代表托管服务、模型权重或订阅登录也采用相同许可。[PI2][OC2][PA3][OH3][GO2][SM2][LC1]

## 四、持续更新与成熟度核验

不使用 star 数当作成熟度证明。这里采用：维护方说明、近期默认分支提交、近期正式发布、公开接口/文档/测试结构。**近期有提交不等于接口稳定，更不保证未来持续维护。**

| 项目 | 核验时默认分支最近提交日期（UTC） | GitHub `releases/latest` 返回的发布 | 判断与注意事项 |
| --- | --- | --- | --- |
| Pi | 2026-11-16 | `v1.5.2`，2026-11-10 | 活跃；以当前官方仓库为准，不误用旧 fork |
| OpenCode | 2026-11-16 | `v1.19.5`，2026-10-28 | 活跃；本次源码来自 `dev`，其中 AI 包版本为 `2.3.0`，不能等同于该正式发布 |
| PydanticAI | 2026-11-16 | `v2.68.0`，2026-11-12 | 活跃；包元数据标为 Production/Stable，低层接口有专门文档 |
| OpenHands Software Agent SDK | 2026-11-16 | `v1.62.0`，2026-11-11 | 活跃；SDK 是官方 CLI/产品使用的执行引擎 |
| Goose | 2026-11-16 | `v1.59.2`，2026-11-16 | 应用活跃；不能把应用版本成熟度套到 `0.1.0-alpha.13` 的 provider crate 上 |
| smolagents | 2026-11-15 | `v1.26.0`，2026-05-29 | 主线仍有更新，但正式发布相较其他候选更久；主线为 `1.27.0.dev0` |
| LangChain | 2026-11-15 | `langchain-core==1.8.1`，2026-11-15 | 活跃；monorepo 的最新 release 不代表全部集成包同时更新 |
| LiteLLM（补充底座） | 2026-11-16 | `v1.109.1`，2026-11-12 | 活跃；核心与 enterprise 代码许可不同 |

数据来自各官方仓库的 GitHub REST 元数据、默认分支 commits 和 releases/latest。每个候选下方的一手资料均固定到本次核验的提交；发布记录可从 [Pi](https://github.com/earendil-works/pi/releases)、[OpenCode](https://github.com/anomalyco/opencode/releases)、[PydanticAI](https://github.com/pydantic/pydantic-ai/releases)、[OpenHands SDK](https://github.com/OpenHands/software-agent-sdk/releases)、[Goose](https://github.com/aaif-goose/goose/releases)、[smolagents](https://github.com/huggingface/smolagents/releases)、[LangChain](https://github.com/langchain-ai/langchain/releases)、[LiteLLM](https://github.com/BerriAI/litellm/releases) 复查。

## 五、逐项分析：拿什么、怎么拿、代价是什么

### 1. PydanticAI：重视源码分工与可选依赖的 Python 候选

**为什么适合：** 模型层的分工不是按厂商随意堆文件，而是明确区分：

```text
Agent                  工具循环、运行控制（可以不用）
  ↓
direct / Model         统一请求、响应、流式调用
  ├─ models/           对应协议与 SDK 的消息转换
  ├─ providers/        认证、客户端、连接目标
  ├─ profiles/         模型能力与协议限制
  └─ messages / usage  公共数据契约
```

官方 `direct` 文档明确面向“构建自己的模型抽象、不需要完整 Agent”的场景，提供同步/异步、流式/非流式以及工具定义传入能力。模型可以直接调用，不需要先建立一个 PydanticAI Agent。[PA1][PA2]

**模型覆盖：** 官方列出 OpenAI、Anthropic、Google、Bedrock、Azure、DeepSeek、Ollama、OpenRouter、Groq、Mistral、xAI、Z.AI 等；另有 OpenAI-compatible 接口和云身份路径。覆盖范围明显超出 OMT 当前注册表，但仍应逐模型核验工具/推理/多模态能力。[PA1]

**推荐复用方式：** 安装 `pydantic-ai-slim` 加所需厂商 extras，调用公开的 `direct`/Model 接口；需要改协议时再考虑固定提交的局部 fork。`slim` 只是减少可选依赖，**并不是只包含 models 的独立发行包**；其清单仍包含 `pydantic-graph` 等基础依赖。[PA3]

**不建议：** 只复制 `models/` 和 `providers/`。它们还依赖 profiles、消息、工具定义、usage、异常及内部辅助模块，表面目录清楚不等于复制两个目录就能运行。

**对 OMT 的难点：** 输入输出不是 LangChain 消息；要转换工具调用、reasoning、签名/opaque 数据、usage 和流式增量，并实现当前执行图需要的聊天模型行为。技术上可行，但必须把 Adapter 当作正式工程量，不能说“改个 import”。

**结论：** 能满足“厂商接口已有实现，不自行重写”的要求；与 LiteLLM 相比，应权衡它清楚的职责分工、可选依赖，以及当前 LangChain 执行层所需的统一 Adapter 成本。

### 2. Pi：已经是可以单独拿走的 AI 包

当前官方仓库为 [`earendil-works/pi`](https://github.com/earendil-works/pi)；旧 `badlogic/pi-mono` 地址在本次 GitHub 查询中重定向到该仓库。当前包名为 **`@earendil-works/pi-ai`**，不要把旧教程中的包名或第三方 fork 当成当前主线。[PI2]

**模块划分：**

```text
packages/ai/             统一模型层、provider、认证、目录、消息与事件
packages/agent/          Agent 执行循环
packages/coding-agent/   编码产品层（不是复用 AI 层的必需入口）
```

AI 包公开 `Models`/Provider 组织方式，支持统一调用与厂商特有选项、模型目录、工具参数增量、reasoning、usage/cost、取消、OAuth 和凭据存储注入，并专门说明跨提供商历史交接。聊天目录只收录支持 tool calling 的模型，不应理解成“所有存在的模型都收录”。[PI1]

**推荐复用方式：** 直接依赖 AI 包；确需改动时 fork AI 包及必要的同仓公共依赖。其 `package.json` 明确依赖 `pi-schema`、`pi-telemetry` 和厂商 SDK，因此不能承诺只复制 `packages/ai` 就能脱离整个工作区自行构建。[PI2]

**对 OMT 的代价：** Python 无法直接导入 TS 包。现实选择是：

- Node 模型进程 + 明确的 JSON/流式协议，Python 用 `BaseChatModel` Adapter 连接；
- 或移植到 Python，但会自行承担协议修复和上游同步，失去直接升级包的优势。

如果选择前者，必须同时设计进程生命周期、取消、背压、错误投影和敏感凭据传输，而不只是“开一个 HTTP 接口”。

**结论：** 接受跨语言时，Pi 本身就是最直接的答案。没有必要为了找“另一个 Pi”而排除它。

### 3. OpenCode：当前已有独立 AI 包，但要注意版本和 Effect

**本次核验到的事实：** `dev` 分支包含 `packages/ai`，清单名为 `@opencode/ai`、版本 `2.3.0`。README 提供独立的 Promise 接口和 Effect 接口，包含 `generate`、`stream`、统一事件与 provider 子入口；`stream` 是一次模型调用，`loop` 才会执行工具并继续调用模型。[OC1][OC2]

这点很重要：**你只要模型调用层，就使用单次调用，不要把它的 tool loop 再套进现有 LangGraph 工具循环。**

**模块划分：**

```text
packages/ai/                请求、协议、provider、事件、可选工具循环
packages/schema/            同仓公共 schema 依赖
packages/core/              产品运行、provider 配置插件、会话等
models.dev                  产品使用的模型目录来源
```

AI 包的 provider 入口覆盖 OpenAI Chat/Responses、Anthropic、Gemini、Bedrock、OpenAI-compatible 等，并有 DeepSeek、Moonshot、MiniMax、Z.AI 等模块。产品的模型目录、账号连接和 provider 配置不应被误认为全部包含在独立 AI 包内。[OC1][OC2][OC3]

**推荐复用方式：** 若走 TS，先研究 `packages/ai` 的公开入口与打包脚本，再选择固定提交构建或经核实的发行版本；不要只复制旧版 `packages/opencode/src/provider`，那不是本次开发快照的目录结构。

**约束：** 内部基于 Effect，并有 `@opencode/schema: workspace:*`、`effect: catalog:` 等依赖，不能把清单原封不动复制到仓库外就期待安装成功。本次 npm registry 查询遇到 TLS 错误，**没有确认该版本已经可从 npm 单独安装**。[OC2]

**结论：** 代码结构非常值得看，尤其是协议、事件和 provider 分离；但对当前 Python 项目，落地优先级低于 PydanticAI/现有 LangChain。

### 4. OpenHands Software Agent SDK：成熟场景参考，但底层主要是 LiteLLM

重点应看 [`OpenHands/software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk)，不是从整个 Web 产品源码中搜一段 LLM 类。官方 README 将 SDK 定位为 CLI 与产品使用的 Agent 引擎。[OH1]

**复用入口：** `openhands-sdk/openhands/sdk/llm/`，包含 LLM、消息、流、认证、profile store、registry、fallback、options 和模型能力等文件，职责可定位。

**真正值得借鉴：** 编码 Agent 场景的上下文与输出预算、错误分类、重试、工具调用差异、Chat/Responses 路径以及模型特性处理。当前 `LLM` 的实现明确基于 LiteLLM 的 `completion/acompletion` 和 Responses 接口。[OH2]

**局限：** `LLM` 还引用 SDK 的 settings、logger、tool 类型和 utility；完整 SDK 包包含多项并非模型调用本身必需的依赖。源码中还设置 `litellm.modify_params = True`，嵌入现有进程时需审查这类全局副作用。[OH2][OH3]

**结论：** 如果目标是借鉴编码 Agent 的实战修补，优先级高；如果目标只是多厂商支持，直接评估 LiteLLM 通常比再包一层 OpenHands 更简单。不要为复用 LLM 顺便引入它的 Agent/Conversation/Workspace。

### 5. Goose：现在确实拆出了 provider crate，但不是 Python 捷径

当前官方地址为 [`aaif-goose/goose`](https://github.com/aaif-goose/goose)，旧 `block/goose` 在本次查询中重定向到此。

**模块划分：**

- `crates/goose-provider-types`：provider 契约与会话类型；
- `crates/goose-providers`：真实协议/provider 实现，并重导出前者；
- `crates/goose`：Agent、产品配置与运行集成。

官方 README 明确建议：只需要契约依赖 types crate，需要可工作的 provider 依赖 implementations crate。原生模块包括 Anthropic、OpenAI、Gemini、Ollama 等，许多 OpenAI-compatible 服务通过声明式 JSON 配置接入，无须新增 Rust provider 代码。[GO1]

**需要保留的判断：** 这种“契约包 + 实现包 + 声明式 provider”的划分非常符合独立复用目标；但当前 `goose-providers` 版本是 `0.1.0-alpha.13`，不能因为 Goose 应用有正式版本，就认为该 crate 的接口已经稳定。[GO2]

**结论：** 如将来考虑 Rust 底座，很值得看；当前 Python OMT 单为多模型支持引入 Rust FFI/服务进程，不是成本最小方案。

### 6. smolagents：容易读，但“轻量”不等于“独立模型发行包”

`src/smolagents/models.py` 把模型接口、消息与流式 delta 放在容易定位的地方，提供 `LiteLLMModel`、`LiteLLMRouterModel`、`InferenceClientModel`、`OpenAIModel`、`AzureOpenAIModel`、`AmazonBedrockModel`、Transformers、MLX、vLLM 等路径。[SM1]

**优点：** Python、接口直观、适合阅读并借鉴小规模实现。尤其是本地推理与 HF Inference 路线，比只接云端 SDK 的方案更贴近这些需求。

**局限：** `models.py` 还导入自己的 `Tool`、`TokenUsage`、重试、限流等辅助定义；其中 LiteLLM 路径的广泛厂商覆盖来自 LiteLLM，不是 smolagents 自己维护全部协议。已检查的 `ChatMessageStreamDelta` 主要公开正文、工具和 usage 字段，不应未经验证就假定其 reasoning 流与 OMT 契约完全匹配。[SM1][SM2]

**结论：** 适合当轻量参考，不建议为了更多厂商在现有 LangChain 上叠一整套 smolagents，再叠 LiteLLM。

### 7. LangChain：可以保留执行层，但不要求继续逐厂商扩展

`init_chat_model` 提供统一工厂，返回 `BaseChatModel`；厂商协议位于独立集成包，安装主包并不自动安装所有厂商依赖。使用已有集成通常不需要自行实现 HTTP 协议，但仍需逐项安装、配置和维护 OMT 注册接入。这不是用户本次优先要求的“一套现成多厂商底座”。[LC1]

**符合补充需求的用法：** 保留 LangChain/LangGraph 的 Agent 执行、工具和历史，通过一个现成的 `langchain-litellm` 集成使用 LiteLLM。LangChain 在此只是执行框架与统一桥接，不是让你继续分别编写各厂商模块。[LB1]

**结论：** 不应把“保留 LangChain”和“继续自己维护每个厂商适配”画等号；前者可以保留，后者可以交给 LiteLLM。

## 六、首选底座：LiteLLM SDK

**LiteLLM 不是完整 Agent，但它最直接满足“现成实现大量厂商接口、接入一次、按需配置和修改”的要求。**

官方提供 Python SDK 与可自托管 Proxy，两者都用于统一不同模型服务的调用；smolagents 和 OpenHands 的源码也证明它可以作为 Agent 的底层，而不接管 Agent 工具循环。当前目标优先考虑进程内 SDK，不必为了使用 LiteLLM 额外部署网关。[LT1][SM1][OH2]

### 接入一次，而不是再写一组厂商适配

现成的 `langchain-litellm` 提供 `ChatLiteLLM`。核验源码有 `bind_tools`、同步/异步生成、同步/异步流，以及 reasoning/工具增量转换实现；这证明桥接已有实现，但不代替 OMT 的兼容性测试。[LB1][LB2]

概念性配置示例（未执行，不是完整 OMT 补丁；需要对应服务的合法凭据和可用模型）：

```python
from langchain_litellm import ChatLiteLLM

# 都是同一个模型类，不是分别编写三套厂商实现。
openai_model = ChatLiteLLM(model="openai/gpt-4o-mini")
anthropic_model = ChatLiteLLM(model="anthropic/claude-sonnet-4-5")
google_model = ChatLiteLLM(model="gemini/gemini-2.5-flash")
```

模型标识仅示意路由方式，不保证账号权限、未来可用性或全部功能一致。必要的上层工作是一次性接通 OMT 的凭据、模型选择和事件契约；不是每增加一个已支持厂商就重新实现客户端。

### 能删减到什么程度

- **只开放部分 provider/model：** 在 OMT 配置和服务端校验中使用白名单，隐藏并拒绝未开放项。只隐藏 UI 不构成调用限制；白名单也不缩小安装体积。
- **修改个别厂商行为：** LiteLLM 的实现位于 `litellm/llms/<provider>/`，可固定版本后局部 fork。
- **物理删除源码/减依赖：** 不能只删除 provider 目录。`litellm/main.py` 有集中路由和多个 provider 导入，必须同步处理导入、注册、依赖与测试。若“源码精简”比“开箱覆盖”更重要，应同时评估 PydanticAI 的可选 extras 和模型/provider 分工。[LT3]

可选运行路径：

- **进程内 SDK：** OMT → LangChain 的 LiteLLM 集成 → LiteLLM → 厂商；少一个服务，但增加适配与依赖层级，reasoning/工具流要实测。
- **独立网关：** OMT → 经验证的 OpenAI-compatible 集成 → 自托管 LiteLLM Proxy → 厂商；应用侧更统一，但增加服务部署、Key 管理、监控与故障点。

如果走网关，要分别验证 Chat Completions、Responses、reasoning 和厂商扩展字段，不能把“OpenAI-compatible”视为全部特性的无损映射。也不应将当前 Ollama 原生协议路径强行替换掉，除非验证了所需参数与行为。

**许可注意：** 根 LICENSE 明确规定，`litellm/enterprise/` 有独立许可证，其余适用 MIT。不能只看 GitHub 的自动许可证识别，也不能将整个仓库笼统称为纯 MIT。[LT2]

当前 README 还描述了独立 `litellm-core` 发行构建，但注明发布集成仍在推进；本报告不将它当作已核实可直接安装的稳定轻量包。[LT1]

## 七、不优先的方向与筛选原则

- **AutoGen：不满足本次维护要求。** 核验提交的官方 README 明确说明项目已归档、Microsoft 不再维护，并建议转向 Microsoft Agent Framework。即使 GitHub REST 的 `archived` 标志当时仍返回 `false`，也应以维护方的明确停止维护声明为准，不能用“最近仍有提交”判定它适合新项目。[EX1]
- 不因为一个 Agent 能连接很多模型，就认定它有可独立提取的 AI 包。先看其实际调用的是 LiteLLM、其他 SDK，还是自己的协议实现。
- 本次没有穷举所有 Agent。未入选不代表不维护或不成熟，只表示没有在本次证据范围内列为优先候选。
- 开源代码允许修改，不等于允许任意复用厂商订阅登录；API Key、OAuth/订阅方案和模型权重各有独立条款。

## 八、对 OMT 的落地建议

### 路线 A：一次接通 LiteLLM，保留现有执行框架（优先）

```text
现有 CLI / API / SessionManager / LangGraph
                  ↓
       OMT 通用模型配置与允许列表
                  ↓
       ChatLiteLLM（现成 LangChain 桥接）
                  ↓
       LiteLLM SDK（现成多厂商实现）
                  ↓
      OpenAI / Anthropic / Gemini / …
```

把“OMT 的模型后端实现”和“上游 provider/model 选择”区分开：一次接通 LiteLLM 后，已支持厂商通过配置路由，不继续要求给每个厂商新增 OMT 初始化文件。保留配置存储、会话、检查点、工具循环和对外事件契约。

凭据、模型选择、目录能力与现有原生参数的兼容仍需一次性集成；尤其不能把所有服务都当成单一 API Key，也不能假设 LiteLLM 已自动实现 OMT 的登录 UI、完整账号模型发现或 Pi 风格 OAuth。

**适合：** 当前明确的“少写厂商适配，直接复用现成多模型模块”要求。

### 路线 B：做一个 PydanticAI 模型层原型（长期解耦候选）

```text
现有 Agent（LangChain）
           ↓
OMT BaseChatModel Adapter（只转换，不执行工具）
           ↓
PydanticAI direct / models / providers / profiles
           ↓
          厂商
```

先验证两种真实不同协议的离线替身，例如 OpenAI 与 Anthropic，确保一个 Adapter 能承载差异；不要只以两个 OpenAI-compatible 地址证明抽象成立。不要同时移植 Agent 执行循环或会话存储。

**适合：** 希望统一模型契约，愿意承担 Adapter 和消息兼容成本，但保持 Python。

### 路线 C：直接复用 Pi AI 包（接受跨语言时）

将 Pi AI 作为独立模型进程，通过明确协议接入现有 Python 模型 Adapter。只复用模型调用，不迁移工具执行权。优先于手工将 Pi 所有厂商实现翻译成 Python，因为后者会让你重新成为维护每个厂商的人。

**适合：** Pi 的模型/认证/跨厂商能力确实是刚需，并接受 Node 运行时与进程边界。

### 替换模型层前的最低验收清单

以下是建议的后续原型验收范围，**本次未执行**：

1. 同步、异步、流式、非流式调用保留正文、finish reason 与 usage。
2. 工具调用 ID、分段 JSON 参数、并行调用及工具结果回传正确；工具只由原有执行层执行一次。
3. reasoning 与正文分开，不丢签名/opaque 数据；不把 `none/low/high` 当成所有厂商通用参数。
4. 多轮历史可持久化并恢复；原 LangGraph 检查点兼容性明确，不能默默损失字段。
5. 模型切换时处理不兼容的 reasoning、server-side ID 和原生内容块，不假设无损通用。
6. 取消真正关闭底层流与连接；异常、超时、429、401、断流有稳定行为；不同层的重试不叠加失控。
7. Key 不进入日志；自定义地址与凭据目标一致；OAuth 刷新与文件写入锁行为独立审查。
8. 目录能力区分“已知支持”“未知”“不支持”，不凭模型名字猜能力。
9. 所有默认测试隔离用户配置，使用假 HTTP/SDK 和临时文件；真实模型验证须另行授权。

## 九、最终推荐顺序

1. **LiteLLM SDK + 现成 ChatLiteLLM 桥接：当前 OMT 首选。** 重点是复用已实现的厂商适配，而不是继续逐个写；它不是 Agent，但正是 Agent 使用的这类模型模块。
2. **PydanticAI：Python 下更重视源码职责分工与按需依赖时考虑。** 厂商实现也已存在，主要新增工作是统一接回现有 LangChain，而非重新写各厂商协议。
3. **Pi AI：接受 TypeScript/模型进程时，最符合独立 AI 包的形态。** 不必先拆整个 Agent。
4. **OpenCode `packages/ai`：另一套 TS 现成实现与拆包参考。** 先核实版本、发布与构建链。

OpenHands SDK 和 smolagents 可证明底座复用路线、提供策略参考；不必为了使用其底层 LiteLLM 再引入整套包装。Goose 适合 Rust 方向，不是当前 Python 项目的优先项。

综合而言：**先接一个现成多厂商模块，已支持厂商只配不写；只对确实缺少的能力局部修改。配置删减与源码裁剪分开评估，不把“一次集成”夸大成“零适配、任意删目录”。**

## 十、补充核验：能否保留“在线拉取厂商模型列表，再选择模型”

用户进一步明确：现有交互不仅要统一聊天调用，还要选择厂商后，在线查询该厂商的模型列表供用户选择。这是完整替换的硬要求，不能用静态目录冒充。

### 当前 OMT 的实际行为

本地 `prepare_provider_login → discover_models → list_provider_models` 在登录/选择厂商时刷新列表，然后由用户选定模型。DeepSeek 请求官方 `/models`，Ollama 请求服务 `/api/tags`；失败时是否使用本地缓存由 OMT 根据已有凭据与配置控制。现有远程列表主要提供模型 ID；DeepSeek 的思考等级等能力另由本地已确认映射维护，并不是从官网网页自动提取全部参数。

### LiteLLM 有统一入口，但不是所有 provider 都实时发现

已核验 `get_valid_models(check_provider_endpoint=True, custom_llm_provider=..., api_key=..., api_base=...)`。启用 endpoint 检查后，入口会调用 provider 的 `discover_models`；但实际是否联网，取决于该 provider 实现。没有对应发现实现时可走内置目录；Azure 还有专门占位处理。入口本身有缓存，异常可能被捕获并转换成空列表。[LD1][LD2]

| 已核验的 provider | 实际实现 | 能否等同 OMT 当前语义 |
| --- | --- | --- |
| DeepSeek | `get_models` 直接返回 `bundled_provider_models("deepseek")`，不是官方 `/models` 请求 | **不能**；即使入口启用了 endpoint 检查，也不保证联网 |
| Ollama | 请求 `/api/tags`；失败时可能返回内置静态列表；返回名带 `ollama/` 前缀 | 有在线发现，但回退来源和命名需适配，不能直接替换 |
| Gemini | `get_models` 请求带 Key 的 `/models` | 有在线发现；仍需核验分页、筛选、凭据与错误行为是否满足 OMT |

来源分别为固定提交的 [DeepSeek 实现][LD3]、[Ollama 实现][LD4]、[Gemini 实现][LD5]。以上为源码核验，未发送真实目录请求。**返回一个非空列表不能证明 Key 已通过官方验证，也不能证明列表来自当前服务。**

`get_model_info` 与列表发现是另一种能力，用于获取上下文、价格、工具/reasoning 等元信息；其来源可能包括内置目录及部分 provider 的运行时查询，不能统称为“实时从官网获取所有详情”。[LD1]

### 修正后的替换判断

- **保留当前选择界面与流程：可以设计实现。** OMT 控制交互，不必随着模型调用底座改变。
- **LiteLLM 独自原样接管所有目录查询与缓存策略：不能保证，本次已发现 DeepSeek 反例。**
- **用 LiteLLM 接管聊天调用，同时保留现有 DeepSeek/Ollama 的目录加载器：可作为低风险方案。** 但新厂商能否零目录适配，必须逐项核验，不能因此承诺满足用户“所有厂商都不再维护”的目标。
- 若用户要求所有开放厂商都必须实时发现且不自行维护，选型须同时列出调用覆盖和实时发现覆盖；不能继续只按支持模型数量推荐。Pi 等目录也需同样验证，不能未经核验就声称换成它便全部解决。

因此，本报告对 LiteLLM 的完整推荐应收紧为：**成熟的多厂商调用底座候选，而非已经证明满足 OMT 全部模型发现、能力加载和认证交互契约的即插即用模块。**

## 一手资料索引

引用固定到调研提交，避免将之后变化的默认分支当作本次已验证事实。包版本、提交版本与正式发布并不自动相等。

[PI1]: https://github.com/earendil-works/pi/blob/747c217b81980206063a89e46645b362de7ac8b1/packages/ai/README.md
[PI2]: https://github.com/earendil-works/pi/blob/747c217b81980206063a89e46645b362de7ac8b1/packages/ai/package.json
[OC1]: https://github.com/anomalyco/opencode/blob/56625a3e1f8ab68487dee4e723270876d6e840fc/packages/ai/README.md
[OC2]: https://github.com/anomalyco/opencode/blob/56625a3e1f8ab68487dee4e723270876d6e840fc/packages/ai/package.json
[OC3]: https://github.com/anomalyco/opencode/blob/56625a3e1f8ab68487dee4e723270876d6e840fc/services/site/src/docs/content/providers.mdx
[PA1]: https://github.com/pydantic/pydantic-ai/blob/c7586d79b64706f4605f15a29534118813df12a4/docs/models/overview.md
[PA2]: https://github.com/pydantic/pydantic-ai/blob/c7586d79b64706f4605f15a29534118813df12a4/docs/direct.md
[PA3]: https://github.com/pydantic/pydantic-ai/blob/c7586d79b64706f4605f15a29534118813df12a4/pydantic_ai_slim/pyproject.toml
[OH1]: https://github.com/OpenHands/software-agent-sdk/blob/ff6df2923b9451c33607453c508eddb7eb8f8746/README.md
[OH2]: https://github.com/OpenHands/software-agent-sdk/blob/ff6df2923b9451c33607453c508eddb7eb8f8746/openhands-sdk/openhands/sdk/llm/llm.py
[OH3]: https://github.com/OpenHands/software-agent-sdk/blob/ff6df2923b9451c33607453c508eddb7eb8f8746/openhands-sdk/pyproject.toml
[GO1]: https://github.com/aaif-goose/goose/blob/bf6e1df335a3e0ace08afb4a4c913b94356010ee/crates/goose-providers/README.md
[GO2]: https://github.com/aaif-goose/goose/blob/bf6e1df335a3e0ace08afb4a4c913b94356010ee/crates/goose-providers/Cargo.toml
[SM1]: https://github.com/huggingface/smolagents/blob/e1249d373d58db6abc73882ee394f6bb3854c89f/src/smolagents/models.py
[SM2]: https://github.com/huggingface/smolagents/blob/e1249d373d58db6abc73882ee394f6bb3854c89f/pyproject.toml
[LC1]: https://github.com/langchain-ai/langchain/blob/5838640178981fdd4ddcfbb03577cff4a2b5b750/libs/langchain_v1/langchain/chat_models/base.py
[LT1]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/README.md
[LT2]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/LICENSE
[LT3]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/main.py
[LB1]: https://github.com/langchain-ai/langchain-litellm/blob/f5025311dba488226681ea7f72a5d92367bf34d7/README.md
[LB2]: https://github.com/langchain-ai/langchain-litellm/blob/f5025311dba488226681ea7f72a5d92367bf34d7/langchain_litellm/chat_models/litellm.py
[LD1]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/utils.py
[LD2]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/llms/base_llm/base_utils.py
[LD3]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/llms/deepseek/common_utils.py
[LD4]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/llms/ollama/common_utils.py
[LD5]: https://github.com/BerriAI/litellm/blob/5c540976f603ff8bed19ebf846a0604a942d64ac/litellm/llms/gemini/common_utils.py
[EX1]: https://github.com/microsoft/autogen/blob/8390985108cb1e3881f5f7297765758d8ad2540c/README.md

### 调研限制

- 部分官方文档站点抓取被网络地址安全校验阻止，改读官方 GitHub 中对应文档源码，未放宽安全配置。
- npm registry 查询出现 TLS 错误，因此没有确认 OpenCode 开发分支 AI 包的独立发布状态。
- 活跃度是查询时点快照，成熟度是结合发布、文档与结构的判断；不承诺所有厂商、功能或部署方式均达到相同稳定性。
- 本次仅新增调研文档及导航；没有修改后端实现、依赖或锁文件，也没有接触用户凭据和运行数据库。

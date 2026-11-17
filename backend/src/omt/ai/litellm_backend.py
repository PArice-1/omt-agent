"""统一使用 LiteLLM 的目录与模型实现，不包含厂商 HTTP 协议或原生 SDK 回退。"""

import os
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from pydantic import ConfigDict, HttpUrl, SecretStr, validate_call

# 只使用安装包自带的能力/价格表，避免导入 SDK 就访问第三方目录。
# 该设置是进程级的，须在首次导入 LiteLLM 前生效；用户显式设置时不覆盖。
_ = os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from langchain_litellm import ChatLiteLLM
from litellm.router_utils.reasoning_effort_capability import resolve_supported_reasoning_efforts


@dataclass(frozen=True)
class ModelCapabilities:
    """SDK 本地能力快照；None 表示未知，空等级元组表示明确没有可用 effort。

    available_levels 保留上层约定的 none 回退项；它不代表服务一定支持关闭推理。
    其他等级完全来自 SDK，既不猜测三档，也不读取 model-store.json 的旧映射。
    """

    supports_reasoning: bool | None
    reasoning_efforts: tuple[str, ...] | None

    @property
    def available_levels(self) -> tuple[str, ...]:
        """保留 SDK 的展示顺序并将应用回退项 none 放在首位，不重复添加。"""
        return ("none", *(level for level in self.reasoning_efforts or () if level != "none"))


def get_model_capabilities(*, provider: str, model: str) -> ModelCapabilities:
    """读取所选厂商/原始模型 ID 的 SDK 元数据，绝不访问模型服务或用户文件。

    优先匹配带厂商的键；裸键仅在所属厂商匹配时使用，避免同名模型串用能力。
    等级解析复用当前固定版本 LiteLLM 的内部解析器，升级依赖须重跑能力测试。
    不调用可能触发 Ollama /api/show 等网络请求的通用 get_model_info。
    无条目或等级不全时保留未知，不阻止已配置模型继续调用，也不回退到本地厂商表。
    """
    route = "ollama_chat" if provider == "ollama" else provider
    for key in dict.fromkeys((f"{provider}/{model}", f"{route}/{model}", model)):
        entry: dict[str, object] | None = litellm.model_cost.get(key)
        if entry is None or (key == model and entry.get("litellm_provider") not in (provider, route)):
            continue
        info = {**entry, "key": key}
        efforts = resolve_supported_reasoning_efforts(info, deployment_is_mapped=True)
        supported = entry.get("supports_reasoning")
        if not isinstance(supported, bool):
            supported = bool(efforts) if efforts is not None else None
        return ModelCapabilities(supported, efforts)
    return ModelCapabilities(None, None)


@validate_call(config=ConfigDict(hide_input_in_errors=True))
def initialize_litellm_model(
    provider: str,
    *,
    model: str,
    base_url: HttpUrl,
    api_key: SecretStr | None = None,
    reasoning_effort: str | None = None,
    **options: object,
) -> BaseChatModel:
    """创建可交给现有 Agent 的模型，构造时不发送聊天请求。

    provider 为 LiteLLM 路由名，model 保留厂商原始 ID（包括斜杠和 Ollama 标签）；
    base_url 为已选目录中的可信服务地址。reasoning_effort 的开启等级原样交给 SDK，
    none 仅在 SDK 明确声明支持关闭时传入；不在 OMT 中重写各厂商 thinking 协议。其他调用选项放入 model_kwargs，
    由 LiteLLM 判断适用性；默认不重试，防止桥接与 SDK 多层重试叠加。
    """
    if not model.strip():
        raise ValueError("模型名称不能为空")
    if api_key is not None and not api_key.get_secret_value().strip():
        raise ValueError("API Key 不能为空")
    parameters = dict(options)
    # Ollama 的 chat 路由使用 /api/chat 并支持工具，不使用文本 completion 路由。
    route = "ollama_chat" if provider == "ollama" else provider
    # none 是上层的默认回退值；支持 reasoning_effort 参数不等于接受 none。
    # 仅 SDK 明确给出关闭等级时发送，否则省略以沿用服务默认；显式开启仍交由 SDK 校验。
    if reasoning_effort is not None and (
        reasoning_effort != "none"
        or "none" in (get_model_capabilities(provider=provider, model=model).reasoning_efforts or ())
    ):
        parameters["reasoning_effort"] = reasoning_effort
    return ChatLiteLLM(
        model=model,
        custom_llm_provider=route,
        api_base=str(base_url).rstrip("/"),
        api_key=api_key.get_secret_value() if api_key is not None else None,
        model_kwargs=parameters,
        max_retries=0,
    )


def list_litellm_models(
    *, provider: str, api_key: SecretStr | None, base_url: HttpUrl,
) -> list[str]:
    """通过 LiteLLM 查询目录，返回去前缀、去重排序后的厂商模型 ID。

    请求启用 check_provider_endpoint，但部分厂商仍由 SDK 返回内置列表；
    非空结果不表示 Key 已经联网验证。SDK 自身的缓存与回退保留，OMT 不补写
    /models 或 /api/tags 请求。异常/空目录转换为安全错误，供上层决定缓存回退。
    """
    try:
        names = litellm.get_valid_models(
            check_provider_endpoint=True,
            custom_llm_provider=provider,
            api_key=api_key.get_secret_value() if api_key is not None else None,
            api_base=str(base_url).rstrip("/"),
        )
        prefix = f"{provider}/"
        result = sorted({name.strip().removeprefix(prefix) for name in names
                         if isinstance(name, str) and name.strip().removeprefix(prefix).strip()})
        if not result:
            raise ValueError("空目录")
        return result
    except Exception:
        raise ValueError("无法通过 LiteLLM 获取模型目录，请检查服务、配置和凭据。") from None

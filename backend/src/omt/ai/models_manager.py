"""用一份可删减的配置表注册 LiteLLM 厂商；不实现厂商请求协议。"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from pydantic import HttpUrl, SecretStr, ValidationError

from . import litellm_backend


OLLAMA_BASE_URL = HttpUrl("http://localhost:11434")

class ModelCatalogLoader(Protocol):
    def __call__(self, *, api_key: SecretStr | None, base_url: HttpUrl) -> list[str]: ...


@dataclass(frozen=True)
class ModelProvider:
    """声明厂商连接与目录能力，保留上层配置接口；默认仅使用 LiteLLM。

    base_url 为可信默认服务地址，requires_api_key=False 仅用于本地免 Key 服务。
    思考能力不放在注册表维护，统一从 LiteLLM 元数据解析。
    initialize/list_models 仍可注入替身，避免测试访问真实服务。
    """

    initialize: Callable[..., BaseChatModel]
    list_models: ModelCatalogLoader
    base_url: HttpUrl
    requires_api_key: bool = True


def _initialize(provider: str, **parameters: Any) -> BaseChatModel:
    """延迟路由到共用初始化入口，测试替换该入口即可隔离所有厂商。"""
    return litellm_backend.initialize_litellm_model(provider=provider, **parameters)


# 这里只声明 UI 可选厂商和可信默认地址；删减条目即可缩小开放范围，不新增 HTTP 适配。
_PROVIDER_URLS = {
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com" ,
    "gemini": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": str(OLLAMA_BASE_URL),
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together_ai": "https://api.together.xyz/v1",
    "xai": "https://api.x.ai/v1",
    # 默认使用国内开放平台地址，与国内站 Key 配套；不自动跨站重试认证。
    "moonshot": "https://api.moonshot.cn/v1",
}

models: dict[str, ModelProvider] = {
    provider: ModelProvider(
        initialize=_initialize,
        list_models=partial(litellm_backend.list_litellm_models, provider=provider),
        base_url=HttpUrl(url),
        requires_api_key=provider != "ollama",
    )
    for provider, url in _PROVIDER_URLS.items()
}


def supported_providers() -> tuple[str, ...]:
    """返回配置表中开放的厂商，不联网；不声称覆盖 LiteLLM 全部认证方式。"""
    return tuple(sorted(models))


def provider_requires_api_key(provider: str) -> bool:
    """读取认证要求；未登记厂商拒绝，不默认当作免认证。"""
    adapter = models.get(provider)
    if adapter is None:
        raise ValueError("模型厂商未注册")
    return adapter.requires_api_key


def list_provider_models(*, provider: str, api_key: SecretStr | None = None) -> list[str]:
    """校验凭据后交给 LiteLLM 列目录，不回退到 OMT 自写的厂商 HTTP 接口。"""
    adapter = models.get(provider)
    if adapter is None:
        raise ValueError("模型厂商未注册")
    if adapter.requires_api_key:
        if api_key is None or not api_key.get_secret_value().strip():
            raise ValueError("API Key 不能为空")
    else:
        api_key = None
    return adapter.list_models(api_key=api_key, base_url=adapter.base_url)


def models_provider(
    provider: str, *, model: str, base_url: HttpUrl, args: dict[str, object],
) -> BaseChatModel:
    """统一创建 LiteLLM 模型；保留认证校验和安全参数异常，不选用原生 SDK。"""
    adapter = models.get(provider)
    if adapter is None:
        raise ValueError("该模型未找到")
    parameters = dict(args)
    if not adapter.requires_api_key:
        _ = parameters.pop("api_key", None)
    elif not parameters.get("api_key"):
        raise ValueError("API Key 不能为空")
    try:
        return adapter.initialize(provider, model=model, base_url=base_url, **parameters)
    except ValidationError as exc:
        raise ValueError("模型参数无效，请检查模型配置。") from exc

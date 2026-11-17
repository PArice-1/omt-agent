"""注册与认证契约：未知厂商、非法参数拒绝；免 Key 不复用旧凭据。"""

from unittest.mock import Mock

import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from omt.ai.models_manager import models, models_provider, supported_providers


def test_registry_is_a_curated_subset_not_only_original_providers() -> None:
    assert {"deepseek", "ollama", "openai", "anthropic", "gemini"} <= set(supported_providers())
    assert len(supported_providers()) == len(models)
    assert not models["ollama"].requires_api_key


@pytest.mark.parametrize("provider", ["", "unknown-provider"])
def test_unknown_provider_is_rejected(provider: str, chat_model_factory: Mock) -> None:
    with pytest.raises(ValueError, match="模型未找到"):
        models_provider(provider, model="example", base_url=HttpUrl("https://example.test"), args={})
    chat_model_factory.assert_not_called()


@pytest.mark.parametrize("key", [None, "", " ", SecretStr("")])
def test_cloud_requires_nonblank_key(key: object, chat_model_factory: Mock) -> None:
    with pytest.raises(ValueError, match="API Key"):
        models_provider("deepseek", model="example", base_url=models["deepseek"].base_url,
                        args={"api_key": key})
    chat_model_factory.assert_not_called()


@pytest.mark.parametrize("parameter,value", [
    ("provider", 123), ("model", 123), ("base_url", "ftp://example.test"),
    ("api_key", 123), ("reasoning_effort", True),
])
def test_registered_initializer_validates_types_before_sdk(
    parameter: str, value: object, chat_model_factory: Mock,
) -> None:
    """注册回调仍保留运行时校验；错误参数不能触发客户端构造或请求。"""
    options: dict[str, object] = {"provider": "deepseek", "model": "example",
                                  "base_url": models["deepseek"].base_url, "api_key": SecretStr("fake-key")}
    options[parameter] = value
    with pytest.raises(ValidationError):
        _ = models["deepseek"].initialize(**options)
    chat_model_factory.assert_not_called()


def test_ollama_discards_compatibility_key_and_does_not_mutate_options(chat_model_factory: Mock) -> None:
    options: dict[str, object] = {"api_key": SecretStr("must-not-use"), "reasoning_effort": "none", "num_ctx": 4096}
    models_provider("ollama", model="qwen3:8b", base_url=models["ollama"].base_url, args=options)
    forwarded = chat_model_factory.call_args.kwargs
    assert forwarded["api_key"] is None
    assert forwarded["model_kwargs"] == {"num_ctx": 4096}  # SDK 未声明关闭能力时不发送 none。
    assert options["api_key"] == SecretStr("must-not-use")


@pytest.mark.parametrize("name", ["", " \n"])
def test_blank_model_is_rejected(name: str, chat_model_factory: Mock) -> None:
    with pytest.raises(ValueError, match="模型名称"):
        models_provider("openai", model=name, base_url=models["openai"].base_url,
                        args={"api_key": SecretStr("test-only-key")})
    chat_model_factory.assert_not_called()

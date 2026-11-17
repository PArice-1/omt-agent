"""目录统一走 LiteLLM，不再访问 OMT 的厂商 HTTP 实现；使用 SDK 边界替身。"""

from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from omt.ai import litellm_backend
from omt.ai.models_manager import list_provider_models, models, supported_providers


@pytest.mark.parametrize("provider", supported_providers())
def test_catalog_uses_litellm_and_preserves_raw_ids(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = Mock(return_value=[f"{provider}/vendor/model:tag", " z-model ", "z-model", " "])
    monkeypatch.setattr(litellm_backend.litellm, "get_valid_models", sdk)
    key = SecretStr("fake-key") if models[provider].requires_api_key else None
    assert list_provider_models(provider=provider, api_key=key) == ["vendor/model:tag", "z-model"]
    sdk.assert_called_once_with(check_provider_endpoint=True, custom_llm_provider=provider,
                                api_key="fake-key" if key else None, api_base=str(models[provider].base_url).rstrip("/"))


@pytest.mark.parametrize("response", [[], ["", " "], ["deepseek/"], RuntimeError("fake-private-marker")])
def test_empty_or_failed_catalog_is_a_safe_error(response: object, monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
    monkeypatch.setattr(litellm_backend.litellm, "get_valid_models", sdk)
    with pytest.raises(ValueError, match="LiteLLM") as raised:
        list_provider_models(provider="deepseek", api_key=SecretStr("fake-key"))
    assert "fake-private-marker" not in str(raised.value)


@pytest.mark.parametrize("provider,key", [("unknown", SecretStr("fake-key")), ("openai", None)])
def test_catalog_rejects_invalid_connection_before_sdk(
    provider: str, key: SecretStr | None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = Mock()
    monkeypatch.setattr(litellm_backend.litellm, "get_valid_models", sdk)
    with pytest.raises(ValueError):
        list_provider_models(provider=provider, api_key=key)
    sdk.assert_not_called()


def test_static_catalog_does_not_trigger_extra_official_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 的静态回退也直接采用，不再补发旧 DeepSeek /models 请求。"""
    sdk = Mock(return_value=["deepseek/deepseek-chat"])
    monkeypatch.setattr(litellm_backend.litellm, "get_valid_models", sdk)
    assert list_provider_models(provider="deepseek", api_key=SecretStr("not-a-validated-key")) == ["deepseek-chat"]

"""只读真实 LiteLLM 元数据，验证多厂商等级、未知能力及无网络约束。"""

import pytest

from omt.ai import litellm_backend
from omt.ai.litellm_backend import get_model_capabilities


@pytest.mark.parametrize("model,expected", [
    ("gpt-5", ("minimal", "low", "medium", "high")),
    ("gpt-5.1", ("none", "low", "medium", "high")),
])
def test_bundled_sdk_models_supply_actual_levels(model: str, expected: tuple[str, ...]) -> None:
    """实际安装包的等级不是 OMT 的 DeepSeek 表，也不是所有模型统一三档。"""
    capabilities = get_model_capabilities(provider="openai", model=model)
    assert capabilities.supports_reasoning is True
    assert capabilities.reasoning_efforts == expected
    assert capabilities.available_levels == ("none", *(level for level in expected if level != "none"))


@pytest.mark.parametrize("provider", ["deepseek", "gemini", "anthropic", "ollama"])
def test_sdk_metadata_is_used_for_every_provider(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """在 SDK 元数据中声明不连续等级，OMT 不额外补造 medium。"""
    monkeypatch.setitem(litellm_backend.litellm.model_cost, f"{provider}/test-capability", {
        "litellm_provider": provider, "mode": "chat", "supports_reasoning": True,
        "reasoning_effort_levels": ["high", "low", "max"],
    })
    capabilities = get_model_capabilities(provider=provider, model="test-capability")
    assert capabilities.reasoning_efforts == ("low", "high", "max")
    assert capabilities.available_levels == ("none", "low", "high", "max")


def test_unknown_levels_are_not_confused_with_unsupported_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "openai/test-reasoning", {
        "litellm_provider": "openai", "mode": "chat", "supports_reasoning": True,
    })
    unknown = get_model_capabilities(provider="openai", model="test-reasoning")
    assert unknown.supports_reasoning is True and unknown.reasoning_efforts is None
    assert unknown.available_levels == ("none",)
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "openai/test-reasoning", {
        "litellm_provider": "openai", "mode": "chat", "supports_reasoning": False,
    })
    unsupported = get_model_capabilities(provider="openai", model="test-reasoning")
    assert unsupported.supports_reasoning is False and unsupported.reasoning_efforts == ()


def test_off_catalog_model_and_other_provider_metadata_do_not_guess_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "test-off-catalog", {
        "litellm_provider": "anthropic", "supports_reasoning": True,
        "reasoning_effort_levels": ["high"],
    })
    capabilities = get_model_capabilities(provider="openai", model="test-off-catalog")
    assert capabilities.supports_reasoning is None and capabilities.reasoning_efforts is None
    assert capabilities.available_levels == ("none",)

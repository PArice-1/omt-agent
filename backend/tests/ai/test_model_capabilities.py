"""用 LiteLLM 本地元数据验证多厂商等级、Flash 兼容及未知能力。"""

from collections.abc import Callable

import pytest

from omt.ai import litellm_backend
from omt.ai.litellm_backend import get_context_window, get_model_capabilities


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


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-flash"])
def test_deepseek_flash_exposes_documented_thinking_levels(model: str) -> None:
    """真实 SDK 数据下，旧 ID 和现用 ID 都必须提供 DeepSeek 公布的有效档位。"""
    capabilities = get_model_capabilities(provider="deepseek", model=model)
    assert capabilities.supports_reasoning is True
    assert capabilities.available_levels == ("none", "low", "high", "max")


@pytest.mark.parametrize(("provider", "model", "declared", "expected"), [
    ("deepseek", "deepseek-v4-flash", ("high",), ("none", "high")),
    ("deepseek", "deepseek-v4-flash", (), ("none",)),
    ("deepseek", "test-flash", None, ("none",)),
    ("openrouter", "deepseek-v4-flash", None, ("none",)),
])
def test_deepseek_flash_thinking_fallback_respects_sdk_and_provider(
    provider: str, model: str, declared: tuple[str, ...] | None, expected: tuple[str, ...],
    sdk_reasoning: Callable[[str, str, tuple[str, ...] | None], None],
) -> None:
    """不覆盖 SDK 的明确声明，也不把兼容档位推广到不同模型或厂商。"""
    sdk_reasoning(provider, model, declared)
    assert get_model_capabilities(provider=provider, model=model).available_levels == expected


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


@pytest.mark.parametrize(("entry", "expected"), [
    ({"max_input_tokens": 272000, "max_tokens": 400000, "max_output_tokens": 128000}, 272000),
    ({"max_tokens": 64000}, 64000),
    ({"max_input_tokens": None, "max_tokens": 32000}, 32000),
    ({"max_input_tokens": -1, "max_tokens": 0}, None),
    ({"max_input_tokens": True, "max_output_tokens": 8000}, None),
    ({}, None),
])
def test_context_window_uses_local_metadata_not_output_limit(
    entry: dict[str, object], expected: int | None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不联网，优先输入窗口、兼容旧条目，不将输出相加或把非法值当容量。"""
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "openai/test-window", entry)
    assert get_context_window(provider="openai", model="test-window") == expected


def test_context_window_matches_provider_and_ollama_chat_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """同名裸键不能跨厂商串用，Ollama 也可从 chat 路由读取容量。"""
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "test-window", {
        "litellm_provider": "anthropic", "max_input_tokens": 100000,
    })
    assert get_context_window(provider="openai", model="test-window") is None
    monkeypatch.setitem(litellm_backend.litellm.model_cost, "ollama_chat/test-window", {
        "litellm_provider": "ollama_chat", "max_input_tokens": 8192,
    })
    assert get_context_window(provider="ollama", model="test-window") == 8192


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

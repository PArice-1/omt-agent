"""共用快捷模型目录：只读、本地、过滤无凭据/未注册项。"""

import json
from collections.abc import Callable

import pytest
from pydantic import SecretStr

from omt.core import model_configuration, settings


@pytest.mark.parametrize("provider", ["deepseek", "openai", "gemini"])
def test_configured_choices_use_sdk_levels_without_catalog_writes(
    provider: str, sdk_reasoning: Callable[..., None],
) -> None:
    """缺少 provider 的旧条目也能从所属厂商解析能力，且不写入目录快照。"""
    assert model_configuration.list_configured_models() == []
    sdk_reasoning(provider, "test-reasoner", ("low", "high", "max"))
    _ = model_configuration.save_model_login(
        model_configuration.ModelLogin(provider=provider, api_key=SecretStr("test-only-key"), model_name="test-reasoner"),
        model_names=["unknown", "test-reasoner"],
    )
    directory = settings.root / "agent"
    path = directory / "model-store.json"
    payload = json.loads(path.read_text())
    payload[provider]["models"][0].pop("provider")
    _ = path.write_text(json.dumps(payload))
    before = {file: file.read_bytes() for file in directory.iterdir()}
    choices = model_configuration.list_configured_models()
    assert [(item.provider, item.model) for item in choices] == [(provider, "test-reasoner"), (provider, "unknown")]
    assert choices[0].available_levels == ("none", "low", "high", "max")
    assert choices[1].available_levels == ("none",)
    assert before == {file: file.read_bytes() for file in directory.iterdir()}


@pytest.mark.parametrize("efforts,expected", [
    (None, ("none",)), ((), ("none",)),
    (("max", "high", "low"), ("none", "low", "high", "max")),
    (("minimal", "medium", "high", "xhigh"), ("none", "minimal", "medium", "high", "xhigh")),
    (("not-an-sdk-level", "high"), ("none", "high")),
])
def test_sdk_levels_define_order_and_ignore_legacy_mapping(
    efforts: tuple[str, ...] | None, expected: tuple[str, ...], sdk_reasoning: Callable[..., None],
) -> None:
    sdk_reasoning("deepseek", "local", efforts)
    directory = settings.root / "agent"
    directory.mkdir(parents=True)
    _ = (directory / "auth.json").write_text(json.dumps({
        "deepseek": {"type": "api_key", "key": "test-only-key"},
    }), encoding="utf-8")
    _ = (directory / "model-store.json").write_text(json.dumps({
        "deepseek": {"models": [{
            "id": "local", "baseUrl": "https://example.test", "thinkingLevelMap": {"z-custom": "max", "low": "high"},
        }]},
    }), encoding="utf-8")
    before = {path: path.read_bytes() for path in directory.iterdir()}
    choices = model_configuration.list_configured_models()
    assert len(choices) == 1 and choices[0].available_levels == expected
    assert before == {path: path.read_bytes() for path in directory.iterdir()}


@pytest.mark.parametrize("key", [None, "", " "])
def test_choices_exclude_models_without_saved_credentials(key: str | None) -> None:
    directory = settings.root / "agent"
    directory.mkdir(parents=True)
    (directory / "model-store.json").write_text(json.dumps({
        "deepseek": {"models": [{"id": "local", "baseUrl": "https://example.test"}]},
    }), encoding="utf-8")
    if key is not None:
        (directory / "auth.json").write_text(json.dumps({"deepseek": {"type": "api_key", "key": key}}), encoding="utf-8")
    assert model_configuration.list_configured_models() == []
    assert not (directory / "settings.json").exists()


def test_choices_skip_unregistered_and_mismatched_provider_entries() -> None:
    directory = settings.root / "agent"
    directory.mkdir(parents=True)
    (directory / "auth.json").write_text(json.dumps({
        name: {"type": "api_key", "key": "test-only-key"} for name in ("deepseek", "other")
    }), encoding="utf-8")
    (directory / "model-store.json").write_text(json.dumps({
        "deepseek": {"models": [{"id": "valid", "baseUrl": "https://example.test"},
                                 {"id": "mismatch", "provider": "other", "baseUrl": "https://example.test"}]},
        "other": {"models": [{"id": "other", "baseUrl": "https://example.test"}]},
    }), encoding="utf-8")
    assert [item.model for item in model_configuration.list_configured_models()] == ["valid"]

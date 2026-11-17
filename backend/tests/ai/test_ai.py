"""通过模型门面验证所有已开放厂商都使用同一个现成桥接，不走原生 SDK。"""

from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr

from omt.ai import litellm_backend
from omt.ai.model import Model
from omt.ai.models_manager import models, supported_providers


@pytest.mark.parametrize("provider", supported_providers())
def test_all_providers_use_common_litellm_bridge(
    provider: str, chat_model_factory: Mock, chat_model: FakeListChatModel,
) -> None:
    key = SecretStr("test-only-key") if models[provider].requires_api_key else None
    client = Model(provider, model="vendor/model:tag", base_url=models[provider].base_url,
                   api_key=key, temperature=0)
    assert client.model is chat_model
    assert client.model.invoke("输入").content == "这是本地测试回复"
    call = chat_model_factory.call_args.kwargs
    assert call["model"] == "vendor/model:tag"
    assert call["custom_llm_provider"] == ("ollama_chat" if provider == "ollama" else provider)
    assert call["model_kwargs"] == {"temperature": 0}
    assert call["api_base"] == str(models[provider].base_url).rstrip("/")
    assert call["api_key"] == ("test-only-key" if key else None)
    assert call["max_retries"] == 0


def test_constructor_does_not_return_a_model_on_failure(chat_model_factory: Mock) -> None:
    failure = RuntimeError("假初始化失败")
    chat_model_factory.side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        Model("deepseek", model="example", base_url=models["deepseek"].base_url,
              api_key=SecretStr("test-only-key"))
    assert raised.value is failure


@pytest.mark.parametrize("effort", ["none", "high"])
def test_shared_none_contract_does_not_break_non_reasoning_models(
    effort: str, chat_model_factory: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上层继续传 none；适配层用 SDK 能力表处理，显式开启不被静默丢弃。"""
    capabilities = Mock(return_value=["temperature", "reasoning_effort"])
    monkeypatch.setattr(litellm_backend.litellm, "get_supported_openai_params", capabilities)
    _ = Model("openai", model="gpt-4o", base_url=models["openai"].base_url,
              api_key=SecretStr("fake-key"), reasoning_effort=effort)
    options = chat_model_factory.call_args.kwargs["model_kwargs"]
    assert options == ({} if effort == "none" else {"reasoning_effort": "high"})
    # 参数受支持也不能证明 none 值可用；关闭能力必须来自 SDK 等级声明。
    capabilities.assert_not_called()

"""统一模型层的工厂替身；保留 Model、注册表与 LiteLLM 参数转换，不访问网络。"""

import socket
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from omt.ai import litellm_backend


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """即使 SDK 的客户端接缝变化，也必须在解析域名/连接前阻断真实网络。"""
    def deny(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("模型层测试禁止真实网络")

    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def chat_model() -> FakeListChatModel:
    return FakeListChatModel(responses=["这是本地测试回复"])


@pytest.fixture
def chat_model_factory(monkeypatch: pytest.MonkeyPatch, chat_model: FakeListChatModel) -> Mock:
    factory = Mock(return_value=chat_model)
    monkeypatch.setattr(litellm_backend, "ChatLiteLLM", factory)
    return factory

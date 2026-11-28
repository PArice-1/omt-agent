"""真实 ChatLiteLLM/LiteLLM 配 MockTransport，检验统一层的线协议。"""

import asyncio
from collections.abc import Callable
import json
from typing import cast

import httpx
import pytest
from pydantic import HttpUrl, SecretStr

from omt.ai.model import Model
import litellm
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("effort", ["none", "high"])
def test_deepseek_uses_litellm_translation_and_preserves_reasoning(
    asynchronous: bool, effort: str, sdk_reasoning: Callable[..., None],
) -> None:
    sdk_reasoning("deepseek", "deepseek-chat", ("none", "high"))
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "id": "fake-reply", "object": "chat.completion", "created": 1, "model": "deepseek-chat",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "答案",
                                                   "reasoning_content": "推理"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    async def execute() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            sdk = AsyncHTTPHandler(transport=httpx.MockTransport(respond))
            sdk.client = transport
            client = Model("deepseek", model="deepseek-chat", base_url=HttpUrl("https://example.test/proxy/v1"),
                           api_key=SecretStr("fake-sdk-key"), reasoning_effort=effort, client=sdk)
            assert not requests
            message = await client.model.ainvoke("问题")
            assert message.content == "答案" and message.additional_kwargs["reasoning_content"] == "推理"
            assert message.usage_metadata is not None and message.usage_metadata["total_tokens"] == 5

    if asynchronous:
        asyncio.run(execute())
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            sdk = HTTPHandler(client=transport)
            client = Model("deepseek", model="deepseek-chat", base_url=HttpUrl("https://example.test/proxy/v1"),
                           api_key=SecretStr("fake-sdk-key"), reasoning_effort=effort, client=sdk)
            assert not requests
            message = client.model.invoke("问题")
            assert message.content == "答案" and message.additional_kwargs["reasoning_content"] == "推理"
            assert message.usage_metadata is not None and message.usage_metadata["total_tokens"] == 5
    assert len(requests) == 1 and requests[0].url.path == "/proxy/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["model"] == "deepseek-chat"
    assert body["thinking"] == {"type": "disabled" if effort == "none" else "enabled"}
    assert "reasoning_effort" not in body  # 由 LiteLLM 自身转换，不再要求等同旧适配的请求体。


@pytest.mark.parametrize(("asynchronous", "model"), [(False, "deepseek-v4-flash"), (True, "deepseek-flash")])
@pytest.mark.parametrize("effort", ["none", "low", "high", "max"])
def test_deepseek_flash_sends_selected_thinking_level(asynchronous: bool, model: str, effort: str) -> None:
    """拦截真实 SDK 的 HTTP 请求，确认选中的强度没有被降成单纯的思考开关。"""
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "id": "fake-reply", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "答案"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    def make_model(handler: HTTPHandler | AsyncHTTPHandler) -> Model:
        return Model("deepseek", model=model, base_url=HttpUrl("https://example.test/v1"),
                     api_key=SecretStr("fake-key"), reasoning_effort=effort, client=handler,
                     extra_body={"user": "flash-regression"})

    async def execute() -> None:
        handler = AsyncHTTPHandler(transport=httpx.MockTransport(respond))
        try:
            assert (await make_model(handler).model.ainvoke("问题")).content == "答案"
        finally:
            await handler.client.aclose()

    if asynchronous:
        asyncio.run(execute())
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            assert make_model(HTTPHandler(client=transport)).model.invoke("问题").content == "答案"

    assert len(requests) == 1 and requests[0].url.path == "/v1/chat/completions"
    body = cast(dict[str, object], json.loads(requests[0].content))
    assert body["model"] == model and body["user"] == "flash-regression"
    if effort == "none":
        assert body["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in body
    else:
        assert body["thinking"] == {"type": "enabled"}
        assert body.get("reasoning_effort") == effort


@pytest.mark.parametrize("asynchronous", [False, True])
def test_sdk_authentication_failure_propagates_without_fake_answer(asynchronous: bool) -> None:
    """真实 SDK 将受控 HTTP 401 变成异常，上层仍可按原失败路径处理。"""
    attempts: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(401, json={"error": {"message": "fake-denied", "type": "authentication_error"}})

    async def execute() -> None:
        handler = AsyncHTTPHandler(transport=httpx.MockTransport(respond))
        try:
            client = Model("deepseek", model="deepseek-chat", base_url=HttpUrl("https://example.test/v1"),
                           api_key=SecretStr("fake-key"), client=handler)
            with pytest.raises(litellm.AuthenticationError):
                _ = await client.model.ainvoke("问题")
        finally:
            await handler.client.aclose()

    if asynchronous:
        asyncio.run(execute())
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            client = Model("deepseek", model="deepseek-chat", base_url=HttpUrl("https://example.test/v1"),
                           api_key=SecretStr("fake-key"), client=HTTPHandler(client=transport))
            with pytest.raises(litellm.AuthenticationError):
                _ = client.model.invoke("问题")
    assert len(attempts) == 1

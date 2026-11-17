"""真实 LiteLLM Ollama 路由配内存传输，确认不再依赖 ChatOllama 或 OMT HTTP。"""

import asyncio
from collections.abc import Callable
import json

import httpx
import pytest
from pydantic import SecretStr

from omt.ai.model import Model
from omt.ai.models_manager import models
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler


@pytest.mark.parametrize("asynchronous", [False, True])
def test_litellm_native_ollama_request_and_reasoning(
    asynchronous: bool, sdk_reasoning: Callable[..., None],
) -> None:
    """在 SDK 的 HTTP 客户端接缝替换传输；保留实际参数映射与响应解析。"""
    sdk_reasoning("ollama", "qwen3:8b", ("none", "high"))
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "model": "qwen3:8b", "message": {"role": "assistant", "content": "回答", "thinking": "思考"},
            "done": True, "prompt_eval_count": 3, "eval_count": 2,
        })

    async def execute() -> None:
        handler = AsyncHTTPHandler(transport=httpx.MockTransport(respond))
        try:
            client = Model("ollama", model="qwen3:8b", base_url=models["ollama"].base_url,
                           api_key=SecretStr("must-not-use"), reasoning_effort="none", client=handler)
            assert not requests
            message = await client.model.ainvoke("输入")
            assert message.content == "回答"
            assert message.additional_kwargs["reasoning_content"] == "思考"
        finally:
            await handler.client.aclose()

    if asynchronous:
        asyncio.run(execute())
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            handler = HTTPHandler(client=transport)
            client = Model("ollama", model="qwen3:8b", base_url=models["ollama"].base_url,
                           api_key=SecretStr("must-not-use"), reasoning_effort="none", client=handler)
            assert not requests
            message = client.model.invoke("输入")
            assert message.content == "回答"
            assert message.additional_kwargs["reasoning_content"] == "思考"
    assert len(requests) == 1 and requests[0].url.path == "/api/chat"
    body = json.loads(requests[0].content)
    assert body["model"] == "qwen3:8b" and body["think"] is False
    assert "authorization" not in requests[0].headers

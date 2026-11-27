"""通过 HTTP 传输替身验证异步 OMT 会话、请求和异常。"""

import asyncio
import json
from collections.abc import Iterable
from typing import cast

import pytest
from httpx2 import AsyncClient, MockTransport, ReadTimeout, Request, Response

import omt_adapter
from omt_adapter import OmtAdapterError, run_omt


BASE_URL = "http://127.0.0.1:9001"
SESSIONS_URL = f"{BASE_URL}/api/omt/sessions"


def fake_http(
    monkeypatch: pytest.MonkeyPatch,
    responses: Iterable[tuple[int, bytes] | Exception],
) -> list[tuple[str, object]]:
    """使用 HTTPX 的 MockTransport，保留实际请求构造并按顺序返回响应。"""
    pending = iter(responses)
    requests: list[tuple[str, object]] = []

    async def handle(request: Request) -> Response:
        """读取完整 JSON 请求；任何额外请求都使测试失败。"""
        assert request.method == "POST"
        assert request.headers["Content-Type"] == "application/json"
        requests.append((str(request.url), cast(object, json.loads(request.content))))
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        status, content = response
        return Response(status, content=content)

    def client(*, timeout: float, headers: dict[str, str]) -> AsyncClient:
        """用测试传输替换实际连接，不改变超时及 header 配置。"""
        return AsyncClient(transport=MockTransport(handle), timeout=timeout, headers=headers)

    monkeypatch.setattr(omt_adapter, "AsyncClient", client)
    return requests


def test_omt_uses_a_new_session_per_trial_and_preserves_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """直接调用适配器两次，验证独立会话和原始回答。"""
    requests = fake_http(monkeypatch, [
        (201, b'{"session_id":"session-1"}'),
        (200, b'{"status":"completed","answer":"hello\\n"}'),
        (201, b'{"session_id":"session-2"}'),
        (200, b'{"status":"completed","answer":"hello"}'),
    ])

    async def call_twice() -> list[str]:
        """使用同一事件循环执行两次独立请求。"""
        return [await run_omt("请只输出 hello", base_url=BASE_URL + "/", timeout=5) for _ in range(2)]

    assert asyncio.run(call_twice()) == ["hello\n", "hello"]
    assert requests == [
        (SESSIONS_URL, {}),
        (f"{SESSIONS_URL}/session-1/runs", {"message": "请只输出 hello"}),
        (SESSIONS_URL, {}),
        (f"{SESSIONS_URL}/session-2/runs", {"message": "请只输出 hello"}),
    ]


@pytest.mark.parametrize(("response", "match"), [
    ((503, b"private details"), "创建会话.*HTTP 503"),
    ((201, b'{"session_id":""}'), "创建会话.*session_id"),
])
def test_failed_session_does_not_send_instruction(
    monkeypatch: pytest.MonkeyPatch, response: tuple[int, bytes], match: str,
) -> None:
    """创建会话失败时不提交任务指令，也不回显错误响应体。"""
    requests = fake_http(monkeypatch, [response])
    with pytest.raises(OmtAdapterError, match=match) as exc_info:
        _ = asyncio.run(run_omt("hello", base_url=BASE_URL))
    assert requests == [(SESSIONS_URL, {})]
    assert "private details" not in str(exc_info.value)


@pytest.mark.parametrize(("response", "match"), [
    ((200, b"not json"), "提交指令.*JSON"),
    ((200, b'{"status":"completed","answer":null}'), "提交指令.*answer"),
    ((200, b'{"status":"failed","answer":"partial"}'), "提交指令.*completed"),
    (ReadTimeout("timed out"), "提交指令.*超时"),
])
def test_run_errors_are_not_returned_as_answers(
    monkeypatch: pytest.MonkeyPatch, response: tuple[int, bytes] | Exception, match: str,
) -> None:
    """请求失败或响应不符合契约时抛出异常，且不重发有副作用的请求。"""
    requests = fake_http(monkeypatch, [(201, b'{"session_id":"session-1"}'), response])
    with pytest.raises(OmtAdapterError, match=match):
        _ = asyncio.run(run_omt("hello", base_url=BASE_URL))
    assert requests == [(SESSIONS_URL, {}), (f"{SESSIONS_URL}/session-1/runs", {"message": "hello"})]


@pytest.mark.parametrize("timeout", [0, float("inf")])
def test_invalid_timeout_does_not_connect(monkeypatch: pytest.MonkeyPatch, timeout: float) -> None:
    """超时不是有限正数时，不创建服务端会话。"""
    requests = fake_http(monkeypatch, [])
    with pytest.raises(ValueError, match="timeout"):
        _ = asyncio.run(run_omt("hello", base_url=BASE_URL, timeout=timeout))
    assert requests == []

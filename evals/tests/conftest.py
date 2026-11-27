"""为 OMT 评测测试提供默认离线保护。"""

import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """在 DNS 和 TCP 连接前拒绝所有真实网络请求，包括 SDK 后台请求。"""
    def reject(*_args: object, **_kwargs: object) -> None:
        """测试只能通过显式替身访问 OMT 或 LangSmith。"""
        pytest.fail("评测测试不允许真实网络请求")

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)

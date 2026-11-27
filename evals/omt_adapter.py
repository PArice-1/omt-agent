"""将 OMT 非流式 HTTP 接口适配为异步评测目标。"""

from math import isfinite
from typing import cast
from urllib.parse import quote, urlsplit

from httpx2 import AsyncClient, HTTPStatusError, RequestError, TimeoutException


class OmtAdapterError(RuntimeError):
    """OMT 请求或响应无效；调用方不能将它当成正常回答判分。"""


async def run_omt(
    instruction: str,
    *,
    base_url: str = "http://127.0.0.1:8000",
    timeout: float = 60.0,
) -> str:
    """为每次 trial 新建独立会话，异步发送指令后原样返回最终回答。

    base_url 是可信 OMT API 地址；timeout 是 HTTP 连接和读写等操作的超时（秒），
    默认 60，必须为有限正数。取消本地等待不保证服务端停止，也不回滚工具操作。
    不向服务端发送参考答案，不自动重试，不采集 transcript。
    """
    if not isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须是有限正数，单位为秒")
    parts = urlsplit(base_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("base_url 必须是 OMT 的 HTTP(S) 根地址，不能包含认证、查询参数或片段")

    sessions_url = f"{base_url.rstrip('/')}/api/omt/sessions"
    async with AsyncClient(timeout=timeout, headers={"Accept": "application/json"}) as client:
        session = await _post_json(client, sessions_url, {}, operation="创建会话")
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise OmtAdapterError("创建会话失败：响应缺少有效的 session_id")

        result = await _post_json(
            client, f"{sessions_url}/{quote(session_id, safe='')}/runs",
            {"message": instruction}, operation="提交指令",
        )
    if result.get("status") != "completed":
        raise OmtAdapterError("提交指令失败：运行状态不是 completed")
    answer = result.get("answer")
    if not isinstance(answer, str):
        raise OmtAdapterError("提交指令失败：响应缺少文本 answer")
    return answer


async def _post_json(
    client: AsyncClient, url: str, payload: dict[str, str], *, operation: str,
) -> dict[str, object]:
    """发送一次 JSON POST，报告失败阶段及状态码，但不回显服务端内容。"""
    try:
        response = await client.post(url, json=payload)
        _ = response.raise_for_status()
        data = cast(object, response.json())
    except HTTPStatusError as exc:
        raise OmtAdapterError(f"{operation}失败：HTTP {exc.response.status_code}") from None
    except TimeoutException:
        raise OmtAdapterError(f"{operation}失败：请求超时") from None
    except RequestError:
        raise OmtAdapterError(f"{operation}失败：无法请求 OMT API") from None
    except ValueError:
        raise OmtAdapterError(f"{operation}失败：响应不是有效的 JSON") from None
    if not isinstance(data, dict):
        raise OmtAdapterError(f"{operation}失败：响应不是 JSON 对象")
    return cast(dict[str, object], data)

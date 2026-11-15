"""工具错误保护：复用 LangChain 重试，并把参数校验失败交回模型修正。"""

from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import ToolRetryMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import ValidationError
from pydantic_core import InitErrorDetails
from pydantic.v1 import ValidationError as ValidationErrorV1


def _format_argument_error(error: ValidationError | ValidationErrorV1) -> str:
    """将 schema 校验异常转为参数修正模板，不回显整份调用参数。"""
    details = "；".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )
    return f"工具参数错误：{details}。请检查工具参数名称、必填项和类型，修正后请重新调用 tool。"


def _format_tool_error(error: Exception) -> str:
    """重试耗尽后返回工具执行异常，避免将内部 TypeError 等误报为参数错误。"""
    return f"工具错误：{type(error).__name__}: {error}"


class ToolErrorMiddleware(ToolRetryMiddleware):
    """对全部工具应用统一错误策略，重试循环完全交给预置 middleware。

    首次失败后最多重试 3 次（合计最多执行 4 次）。等待单位为秒，
    initial_delay=1、backoff_factor=2、max_delay=8，启用预置的 ±25% jitter；
    本策略的三次等待基准为 1、2、4 秒，抖动后也不会超过 8 秒。
    调用前检查顶层未知参数名，避免默认 schema 静默丢弃额外字段。
    参数 schema 校验错误直接生成 status=error 的工具消息，不等待、不重试；
    其他执行异常重试耗尽后返回工具错误，取消和图控制信号仍向上传播。
    重试不保证幂等性，也不能撤销此前执行产生的副作用。
    """

    def __init__(self) -> None:
        super().__init__(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
            max_delay=8.0,
            jitter=True,
            retry_on=(Exception,),
            on_failure=_format_tool_error,
        )

    @staticmethod
    def _reject_unknown_arguments(request: ToolCallRequest) -> ToolMessage | None:
        """按模型可见的字段名拒绝多余参数，校验失败时不执行或重试工具。

        默认的 Pydantic schema 可能忽略额外字段，因此不能只依赖校验异常。
        使用公开 args 属性获取字段，排除由框架注入的 runtime/state 等参数。
        对显式开放额外字段或使用组合/动态字段的 JSON schema 不做简单白名单
        推断，保留其契约；此处不是完整 JSON Schema 校验器。
        """
        if request.tool is None:
            return None
        schema = request.tool.args_schema
        if isinstance(schema, dict):
            if schema.get("additionalProperties", False) is not False:
                return None
            if "properties" not in schema or any(
                key in schema for key in ("patternProperties", "$ref", "allOf", "anyOf", "oneOf")
            ):
                return None
        unknown = sorted(request.tool_call["args"].keys() - request.tool.args.keys())
        if not unknown:
            return None
        errors: list[InitErrorDetails] = [
            {"type": "extra_forbidden", "loc": (name,), "input": request.tool_call["args"][name]}
            for name in unknown
        ]
        error = ValidationError.from_exception_data(request.tool.name, errors)
        return ToolMessage(
            content=_format_argument_error(error),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    @staticmethod
    def _prepare_request(request: ToolCallRequest) -> ToolCallRequest:
        """仅复制本次调用的错误策略，不修改注册实例或影响并发调用。

        参数类型和值仍使用 BaseTool 的校验回调，保持运行时注入参数、
        schema 默认值和同步/异步工具的原有校验流程。关闭工具自己的
        ToolException 消息转换，避免 MCP 等适配器提前吞掉异常而跳过重试。
        """
        if request.tool is None:
            return request
        return request.override(
            tool=request.tool.model_copy(update={
                "handle_validation_error": _format_argument_error,
                "handle_tool_error": False,
            })
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """同步调用：先拒绝未知参数，再由预置策略执行和重试工具。"""
        error_message = self._reject_unknown_arguments(request)
        if error_message is not None:
            return error_message
        return super().wrap_tool_call(self._prepare_request(request), handler)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """异步调用：先拒绝未知参数，等待和取消语义交给预置实现。"""
        error_message = self._reject_unknown_arguments(request)
        if error_message is not None:
            return error_message
        return await super().awrap_tool_call(self._prepare_request(request), handler)

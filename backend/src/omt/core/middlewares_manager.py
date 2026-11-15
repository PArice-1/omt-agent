"""Agent middleware 的统一组装入口；具体策略各自放在独立文件中。"""

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

from .middlewares.tool_error import ToolErrorMiddleware


def load_middlewares() -> list[AgentMiddleware[Any, Any, Any]]:
    """按包装顺序返回新的 middleware 列表，供每次 Agent 构建和重建使用。

    不缓存 middleware 实例；新增保护策略在此显式登记。
    该列表只由应用组装层安装，底层 Agent 封装仍支持调用方自定义策略。
    """
    return [ToolErrorMiddleware()]

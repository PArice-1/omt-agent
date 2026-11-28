"""会话用量的入口无关投影；累计消耗与最近一次上下文占用严格分开。"""

from collections.abc import Iterable

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel, Field, ValidationError


class TokenCounts(BaseModel):
    """一次模型请求的 token 数；输出已包含服务商计入的 reasoning，不额外累加。"""

    input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(default=0, ge=0, strict=True)
    total_tokens: int = Field(default=0, ge=0, strict=True)


def token_counts(value: object) -> TokenCounts | None:
    """只接受三个非负整数都存在的用量；缺失或非法不能伪装成零消耗。"""
    if not isinstance(value, dict) or not all(key in value for key in TokenCounts.model_fields):
        return None
    try:
        return TokenCounts.model_validate(value)
    except ValidationError:
        return None


class UsageSnapshot(TokenCounts):
    """当前会话已报告用量的累计值，以及最近请求的上下文占用快照。

    context_tokens 取最近一次请求输入加输出的 token 数，不是累计消耗，也不包含
    尚未发送的草稿；新会话为 0，最近请求未报告用量时为 None。context_window
    是当前模型本地元数据声明的窗口，未知为 None。百分比是已使用比例（0～100
    或超限时更大），剩余数最低为 0。usage_complete=False 表示累计只是已知下界。
    """

    context_tokens: int | None = Field(default=0, ge=0)
    context_window: int | None = Field(default=None, gt=0)
    context_used_percent: float | None = None
    context_remaining_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool = True

    def with_window(self, window: int | None) -> "UsageSnapshot":
        """用当前运行模型的窗口补齐百分比和剩余额度，不改变累计值。"""
        known = window is not None and self.context_tokens is not None
        used = self.context_tokens or 0
        return self.model_copy(update={
            "context_window": window,
            "context_used_percent": round(used / window * 100, 2) if known and window else None,
            "context_remaining_tokens": max(0, window - used) if known and window else None,
        })

    def interrupted(self) -> "UsageSnapshot":
        """异常/取消可能丢失正在生成的 usage，仅保留已知累计下界。"""
        return self.model_copy(update={"usage_complete": False, "context_tokens": None}).with_window(self.context_window)

    def add_call(self, counts: TokenCounts | None) -> "UsageSnapshot":
        """计入一条已完成模型消息；未报告 usage 时保留累计下界并清空占用快照。"""
        if counts is None:
            return self.interrupted()
        return UsageSnapshot(
            input_tokens=self.input_tokens + counts.input_tokens,
            output_tokens=self.output_tokens + counts.output_tokens,
            total_tokens=self.total_tokens + counts.total_tokens,
            context_tokens=counts.input_tokens + counts.output_tokens,
            usage_complete=self.usage_complete,
        ).with_window(self.context_window)


def usage_from_messages(messages: Iterable[BaseMessage]) -> UsageSnapshot:
    """从原始检查点消息重建快照；只统计 AI 消息，不估算旧历史或重复累加工具内容。"""
    usage = UsageSnapshot()
    for message in messages:
        if isinstance(message, AIMessage):
            usage = usage.add_call(token_counts(message.usage_metadata))
    return usage


def compact_tokens(value: int) -> str:
    """按十进制 k/m/b 缩写非负 token 数，最多一位小数；临界舍入可升到下一单位。"""
    for scale, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k")):
        if value >= scale or (scale > 1_000 and int(value / (scale / 1_000) * 10 + 0.5) >= 10_000):
            rounded = int(value / scale * 10 + 0.5) / 10
            return f"{rounded:.1f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def format_usage(usage: UsageSnapshot) -> str:
    """CLI 输入框下的统一显示；≥ 表示不完整累计，未知窗口/占用明确显示 --。"""
    prefix = "" if usage.usage_complete else "≥"
    percent = "--" if usage.context_used_percent is None else str(int(usage.context_used_percent + 0.5))
    window = "--" if usage.context_window is None else compact_tokens(usage.context_window)
    return f"{prefix}{compact_tokens(usage.total_tokens)} token {percent}%/{window}"

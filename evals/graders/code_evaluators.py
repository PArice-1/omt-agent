"""基于明确规则的逐条评分，不调用模型。"""

from collections.abc import Mapping
from typing import cast

from langsmith.evaluation import EvaluationResult
from langsmith.schemas import Example, Run


def answer_pair(run: Run, example: Example) -> tuple[str, str]:
    """读取原始实际回答、参考答案；拒绝缺少文本的数据，不把缺失当成空字符串。"""
    # SDK 未标注 Run.outputs 的字典内容；这里只读取单个经过类型校验的字段。
    outputs = cast(Mapping[str, object], run.outputs or {})
    answer = outputs.get("answer")
    expected: object = (example.outputs or {}).get("answer")
    if not isinstance(answer, str) or not isinstance(expected, str):
        raise ValueError("实际和参考输出均须包含字符串 answer")
    return answer, expected


async def exact_match(run: Run, example: Example) -> EvaluationResult:
    """比较原始文本，保留空格、换行和大小写差异。"""
    answer, expected = answer_pair(run, example)
    return EvaluationResult(key="exact_match", score=float(answer == expected))


async def contains_expected(run: Run, example: Example) -> EvaluationResult:
    """检查实际回答是否包含非空参考文本，空参考文本不产生有效分数。"""
    answer, expected = answer_pair(run, example)
    if not expected:
        raise ValueError("contains_expected 要求非空参考答案")
    return EvaluationResult(key="contains_expected", score=float(expected in answer))

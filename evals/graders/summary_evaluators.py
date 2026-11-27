"""对整个 suite Experiment 的运行结果评分。"""

from collections.abc import Sequence

from langsmith.evaluation import EvaluationResult
from langsmith.schemas import Example, Run


def completion_rate(runs: Sequence[Run], examples: Sequence[Example]) -> EvaluationResult:
    """返回无运行错误的 trial 比例（0～1），这不是任务评分的通过率。"""
    if not runs or len(runs) != len(examples):
        raise ValueError("completion_rate 要求每次 trial 有对应的样例，且至少有一次运行")
    return EvaluationResult(key="completion_rate", score=sum(run.error is None for run in runs) / len(runs))

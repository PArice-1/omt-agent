"""按样例的 evaluator 配置，并发执行一次 trial 的所有评分。"""

import logging
from asyncio import TaskGroup
from collections.abc import Awaitable, Callable, Mapping, Sequence

from langsmith.evaluation import EvaluationResult, EvaluationResults
from langsmith.schemas import Example, Run
from pydantic import TypeAdapter

from tasks import EvaluatorNames

from .code_evaluators import contains_expected, exact_match
from .llm_evaluators import LLMJudge, make_llm_correctness
from .summary_evaluators import completion_rate


type Evaluator = Callable[[Run, Example], Awaitable[EvaluationResult]]
type SummaryEvaluator = Callable[[Sequence[Run], Sequence[Example]], EvaluationResult]

EVALUATORS: dict[str, Evaluator] = {
    "exact_match": exact_match,
    "contains_expected": contains_expected,
}
SUMMARY_EVALUATORS: dict[str, SummaryEvaluator] = {"completion_rate": completion_rate}
# Pydantic 支持含校验器的类型别名，TypeForm 未识别其运行时对象。
_NAMES = TypeAdapter[EvaluatorNames](EvaluatorNames)  # pyright: ignore[reportArgumentType]
_LOG = logging.getLogger(__name__)


def get_evaluators(*, judge: LLMJudge | None = None) -> dict[str, Evaluator]:
    """复制逐条评分器注册表；仅显式注入独立评委时提供 llm_correctness。"""
    registry = EVALUATORS.copy()
    if judge is not None:
        registry["llm_correctness"] = make_llm_correctness(judge)
    return registry


def evaluator_names(example: Example, registry: Mapping[str, Evaluator]) -> list[str]:
    """校验并返回 Example 的评分器名单；未知名称不能静默跳过。"""
    metadata: dict[str, object] = example.metadata or {}
    label = metadata.get("task_id") or example.id
    try:
        names = _NAMES.validate_python(metadata.get("evaluators"), strict=True)
    except ValueError as exc:
        raise ValueError(f"任务 {label!r} 的 metadata.evaluators 无效；请检查 JSON 并重新注册") from exc
    unknown = [name for name in names if name not in registry]
    if unknown:
        raise ValueError(f"任务 {label!r} 未找到评分器：{', '.join(unknown)}")
    return names


async def grade_trial(
    run: Run,
    example: Example | None,
    *,
    registry: Mapping[str, Evaluator] = EVALUATORS,
) -> EvaluationResults:
    """LangSmith 的统一评分入口：读取 Example 元数据，并发评分并按配置顺序返回。

    每个评分器接收同一个 Run 和 Example，不能修改它们。单项评分失败时
    返回不带分值的反馈，保留同次 trial 的其他评分；取消信号向上传递。
    """
    if example is None:
        raise ValueError("评分需要对应的 Example")
    if run.error is not None:
        return {"results": []}

    names = evaluator_names(example, registry)
    async with TaskGroup() as group:
        tasks = [group.create_task(_grade_one(name, registry[name], run, example)) for name in names]
    return {"results": [task.result() for task in tasks]}


async def _grade_one(name: str, evaluator: Evaluator, run: Run, example: Example) -> EvaluationResult:
    """隔离单项评分异常，避免把运行失败记成模型答错的 0 分。"""
    try:
        result = await evaluator(run, example)
        if result.key != name:
            raise ValueError("评分结果的 key 与注册名不一致")
        return result
    except Exception as exc:
        _LOG.warning("评分器 %s 失败（%s）", name, type(exc).__name__)
        return EvaluationResult(key=name, comment="评分器执行失败", extra={"error": True})

"""按 suite 组装 Target、远端 Dataset 与评分器，由 LangSmith 执行评测。"""

from asyncio import to_thread
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from statistics import fmean

from langsmith import Client
from langsmith.schemas import Dataset, Example
from langsmith.utils import LangSmithNotFoundError

from graders.graders import SUMMARY_EVALUATORS, evaluator_names, get_evaluators, grade_trial
from graders.llm_evaluators import LLMJudge
from tasks import SuiteConfig, dataset_name


@dataclass(frozen=True)
class SuiteResult:
    """一个 suite 的 Experiment 索引、运行状态和逐条评分均值。

    mean_scores 按评分键汇总已收到的数值分数，运行失败或缺失分数不按零分补齐。
    报告不包含任务原文和工具数据。
    """

    dataset_name: str
    experiment_name: str
    experiment_url: str | None
    trial_count: int
    failed_trials: int
    unscored_trials: int
    mean_scores: dict[str, float]


def _select[T](suite: str, names: list[str], registry: Mapping[str, T]) -> list[T]:
    """按配置顺序解析评分器；未知或重复评分器在执行前拒绝。"""
    if len(set(names)) != len(names):
        raise ValueError(f"suite {suite!r} 的评分器配置有重复名称")
    missing = [name for name in names if name not in registry]
    if missing:
        raise ValueError(f"suite {suite!r} 未找到评分器：{', '.join(missing)}")
    return [registry[name] for name in names]


def _read_dataset(client: Client, name: str) -> tuple[Dataset, list[Example]]:
    """使用同步 SDK 读取整个远端快照，由调用方在线程中执行。"""
    dataset = client.read_dataset(dataset_name=name)
    return dataset, list(client.list_examples(dataset_id=dataset.id))  # pyright: ignore[reportUnknownMemberType]


async def run_suites(
    suites: Mapping[str, SuiteConfig],
    client: Client,
    agent: Callable[[str], Awaitable[str]],
    *,
    trials: int = 1,
    max_concurrency: int = 1,
    upload_runs: bool = True,
    judge: LLMJudge | None = None,
) -> dict[str, SuiteResult]:
    """按配置顺序读取现有 Dataset，每个 suite 发起一次 Experiment。

    trials 是每个样例的重复次数；max_concurrency 是同时运行的 trial 上限，
    两者默认为 1，必须是正整数。suite 依次运行，不叠加并发；同一 trial 的
    评分器并发执行，OMT 会话隔离由 agent 保证。upload_runs 默认上传评测运行与评分，
    设为 False 仍读取远端 Dataset，但不会创建云端 Experiment。
    judge 是启用 llm_correctness 时显式提供的独立评委，不发给被测 Agent。
    """
    if type(trials) is not int or trials < 1:
        raise ValueError("trials 必须是正整数")
    if type(max_concurrency) is not int or max_concurrency < 1:
        raise ValueError("max_concurrency 必须是正整数")
    if not suites:
        raise ValueError("至少选择一个 suite")
    registry = get_evaluators(judge=judge)
    plans = {
        suite: (dataset_name(suite), _select(suite, config.summary_evaluators, SUMMARY_EVALUATORS))
        for suite, config in suites.items()
    }

    # 先检查所有 suite 是否已注册且有样例，避免跑了一半才发现数据集缺失。
    datasets: dict[str, tuple[Dataset, list[Example]]] = {}
    for suite, (name, _) in plans.items():
        try:
            dataset, examples = await to_thread(_read_dataset, client, name)
        except LangSmithNotFoundError:
            raise ValueError(f"suite {suite!r} 的 Dataset {name!r} 尚未注册；请先运行 register_datasets.py") from None
        if not examples:
            raise ValueError(f"Dataset {name!r} 没有样例；请先运行 register_datasets.py")
        for example in examples:
            _ = evaluator_names(example, registry)
        datasets[suite] = dataset, examples

    async def target(inputs: Mapping[str, object]) -> dict[str, str]:
        """只提交任务指令，原样返回 OMT 回答；参考答案只供评委读取。"""
        instruction = inputs.get("instruction")
        if not isinstance(instruction, str):
            raise ValueError("Dataset 样例缺少字符串 instruction")
        return {"answer": await agent(instruction)}

    dispatcher = partial(grade_trial, registry=registry)
    reports: dict[str, SuiteResult] = {}
    for suite, (name, summary_evaluators) in plans.items():
        dataset, examples = datasets[suite]
        # SDK 的 metadata 签名未具体标注 dict 内容；逐条只传一个通用评分入口。
        results = await client.aevaluate(  # pyright: ignore[reportUnknownMemberType]
            target, data=examples, evaluators=[dispatcher], summary_evaluators=summary_evaluators,
            metadata={"suite": suite, "dataset_id": str(dataset.id)}, experiment_prefix=name,
            num_repetitions=trials, max_concurrency=max_concurrency, upload_runs=upload_runs,
        )
        total, failed, unscored = 0, 0, 0
        scores: dict[str, list[float]] = {}
        async for row in results:
            total += 1
            if row["run"].error is not None:
                failed += 1
                continue
            feedback = row["evaluation_results"].get("results", [])
            expected_keys = set(evaluator_names(row["example"], registry))
            actual_keys = {grade.key for grade in feedback if grade.score is not None}
            if expected_keys != actual_keys:
                unscored += 1
            for grade in feedback:
                if grade.score is not None:
                    scores.setdefault(grade.key, []).append(float(grade.score))
        reports[suite] = SuiteResult(
            dataset_name=name, experiment_name=results.experiment_name,
            experiment_url=await results.get_comparison_url() if upload_runs else None,
            trial_count=total, failed_trials=failed, unscored_trials=unscored,
            mean_scores={key: fmean(values) for key, values in scores.items()},
        )
    return reports

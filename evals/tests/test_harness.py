"""用真实 LangSmith runner 加内存 Dataset 替身，验证按 suite 编排评测。"""

import asyncio
from collections.abc import Iterator
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from langsmith import Client
from langsmith.schemas import Dataset, Example, TracerSession
from langsmith.utils import LangSmithNotFoundError

from harness import run_suites
from tasks import SuiteConfig


def test_run_suites_repeats_only_the_instruction_and_groups_results() -> None:
    """评分未通过不是调用失败；所有 suite 独立运行、按名称返回结果。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    examples: dict[str, tuple[Dataset, Example]] = {}
    for suite, instruction in [("smoke", "问候"), ("coding", "写代码")]:
        dataset = Dataset(id=uuid4(), name=f"omt-{suite}", created_at="2025-01-01T00:00:00Z")
        example = Example(id=uuid4(), dataset_id=dataset.id, inputs={"instruction": instruction},
                          outputs={"answer": "hello"}, metadata={"task_id": "case", "evaluators": ["exact_match"]})
        examples[dataset.name] = (dataset, example)

    calls: list[str] = []

    async def agent(instruction: str) -> str:
        """保留换行使第一组严格匹配失败，第二组模拟运行失败。"""
        calls.append(instruction)
        if instruction == "写代码":
            raise RuntimeError("假 Agent 执行失败")
        return "hello\n"

    def read_dataset(*, dataset_name: str) -> Dataset:
        """按 Dataset 名返回测试数据集。"""
        return examples[dataset_name][0]

    def list_examples(*, dataset_id: UUID) -> Iterator[Example]:
        """为指定 Dataset 读取已注册样例。"""
        return (example for dataset, example in examples.values() if dataset.id == dataset_id)

    config = SuiteConfig(summary_evaluators=["completion_rate"])
    with (
        patch.object(Client, "read_dataset", side_effect=read_dataset),
        patch.object(Client, "list_examples", side_effect=list_examples),
    ):
        reports = asyncio.run(run_suites({"smoke": config, "coding": config}, client, agent, trials=2, upload_runs=False))

    assert calls == ["问候", "问候", "写代码", "写代码"]
    assert list(reports) == ["smoke", "coding"]
    assert reports["smoke"].dataset_name == "omt-smoke"
    assert reports["smoke"].trial_count == 2
    assert reports["smoke"].failed_trials == 0
    assert reports["smoke"].unscored_trials == 0
    assert reports["smoke"].mean_scores == {"exact_match": 0.0}
    assert reports["coding"].mean_scores == {}
    assert reports["coding"].failed_trials == 2
    assert reports["coding"].trial_count == 2


@pytest.mark.parametrize(("scenario", "message"), [("unknown", "not_registered"), ("missing", "未注册")])
def test_invalid_suite_configuration_prevents_agent_calls(scenario: str, message: str) -> None:
    """无效评分器和未注册 Dataset 均在 Agent 执行前报告。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)

    async def forbidden_agent(_instruction: str) -> str:
        """这些配置错误下不能调用 Agent。"""
        pytest.fail("不应执行 Agent")

    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    example = Example(id=uuid4(), dataset_id=dataset.id, inputs={"instruction": "hello"},
                      metadata={"task_id": "hello", "evaluators": ["not_registered"]})
    failure = LangSmithNotFoundError("not found") if scenario == "missing" else None
    with (
        patch.object(Client, "read_dataset", return_value=dataset, side_effect=failure),
        patch.object(Client, "list_examples", return_value=[example]),
        pytest.raises(ValueError, match=message),
    ):
        _ = asyncio.run(run_suites({"smoke": SuiteConfig()}, client, forbidden_agent))


def test_uploaded_experiment_links_dataset_and_summary_feedback() -> None:
    """默认上传路径创建关联 Dataset 的 Experiment，并区分逐条与整组评分。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    example = Example(id=uuid4(), dataset_id=dataset.id, inputs={"instruction": "问候"},
                      outputs={"answer": "hello"}, metadata={"task_id": "hello", "evaluators": ["exact_match"]})
    experiment_id, tenant_id = uuid4(), uuid4()
    uploaded: list[tuple[str, object, UUID | None]] = []

    def create_project(name: str, *, reference_dataset_id: UUID, **_kwargs: object) -> TracerSession:
        """生成假实验并验证带上已注册 Dataset 的引用。"""
        assert reference_dataset_id == dataset.id
        return TracerSession(id=experiment_id, tenant_id=tenant_id, name=name,
                             reference_dataset_id=reference_dataset_id, _host_url="https://smith.test")

    def create_feedback(*, key: str, score: object, project_id: UUID | None, **_kwargs: object) -> None:
        """收集实际 SDK 写入的逐条和汇总评分。"""
        uploaded.append((key, score, project_id))

    async def agent(instruction: str) -> str:
        """仅接收指令并返回假回答。"""
        assert instruction == "问候"
        return "hello"

    config = SuiteConfig(summary_evaluators=["completion_rate"])
    with (
        patch.object(Client, "read_dataset", return_value=dataset),
        patch.object(Client, "list_examples", return_value=iter([example])),
        patch.object(Client, "create_project", side_effect=create_project),
        patch.object(Client, "update_project"),
        patch.object(Client, "create_run"),
        patch.object(Client, "update_run"),
        patch.object(Client, "create_feedback", side_effect=create_feedback),
    ):
        report = asyncio.run(run_suites({"smoke": config}, client, agent))["smoke"]

    assert report.experiment_url == (
        f"https://smith.test/o/{tenant_id}/datasets/{dataset.id}/compare?selectedSessions={experiment_id}"
    )
    assert report.mean_scores == {"exact_match": 1.0}
    assert set(uploaded) == {("exact_match", 1.0, None), ("completion_rate", 1.0, experiment_id)}


def test_one_experiment_runs_different_evaluators_and_limits_trial_concurrency() -> None:
    """同一 suite 的样例可选不同数量的评分器；并发上限为 2，不为评分额外跑 Agent。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    examples = [
        Example(id=uuid4(), dataset_id=dataset.id, inputs={"instruction": word}, outputs={"answer": word},
                metadata={"task_id": word, "evaluators": names})
        for word, names in [("hello", ["exact_match"]), ("pong", ["exact_match", "contains_expected"]),
                            ("bye", ["contains_expected"])]
    ]
    calls: list[str] = []
    active, peak = 0, 0
    started_together = asyncio.Event()

    async def agent(instruction: str) -> str:
        """前两个 trial 必须同时在场才完成；第三个验证不会突破并发上限。"""
        nonlocal active, peak
        calls.append(instruction)
        active += 1
        peak = max(peak, active)
        if active == 2:
            started_together.set()
        try:
            _ = await asyncio.wait_for(started_together.wait(), timeout=2)
            return {"hello": "hello", "pong": "结果：pong", "bye": "缺少内容"}[instruction]
        finally:
            active -= 1

    with (
        patch.object(Client, "read_dataset", return_value=dataset),
        patch.object(Client, "list_examples", return_value=examples),
    ):
        result = asyncio.run(run_suites({"smoke": SuiteConfig()}, client, agent, max_concurrency=2, upload_runs=False))

    report = result["smoke"]
    assert sorted(calls) == ["bye", "hello", "pong"]
    assert peak == 2
    assert report.trial_count == 3
    assert report.failed_trials == report.unscored_trials == 0
    assert report.mean_scores == {"exact_match": 0.5, "contains_expected": 0.5}

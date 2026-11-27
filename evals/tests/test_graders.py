"""验证统一评分入口按 Example 并发分发，保留独立的反馈。"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from langsmith.evaluation import EvaluationResult
from langsmith.schemas import Example, Run

from graders.graders import Evaluator, get_evaluators, grade_trial


def sample_run(answer: str | None) -> Run:
    """构造已完成的 SDK Run；空缺的实际回答留给评分器判断。"""
    run_id = uuid4()
    return Run(id=run_id, name="target", start_time=datetime.now(UTC), run_type="chain",
               trace_id=run_id, outputs={"answer": answer} if answer is not None else None)


def test_dispatch_starts_both_graders_and_keeps_success_if_one_fails() -> None:
    """两个异步评分器必须同时开始；一个报错不会抹掉另一个已有的分数。"""
    run = sample_run("hello")
    example = Example(id=uuid4(), metadata={"task_id": "hello", "evaluators": ["first", "second"]})
    started: set[str] = set()
    both_active = asyncio.Event()

    async def rendezvous(name: str) -> None:
        """若两个评分器不是并发启动，等待会超时。"""
        started.add(name)
        if len(started) == 2:
            both_active.set()
        _ = await asyncio.wait_for(both_active.wait(), timeout=2)

    async def first(actual: Run, reference: Example) -> EvaluationResult:
        """接收同次 trial 的 Run 和 Example，评分成功。"""
        assert (actual, reference) == (run, example)
        await rendezvous("first")
        return EvaluationResult(key="first", score=1.0)

    async def second(actual: Run, reference: Example) -> EvaluationResult:
        """与第一个评分器并发，但模拟评委失败。"""
        assert (actual, reference) == (run, example)
        await rendezvous("second")
        raise OSError("测试评委不可用")

    registry: dict[str, Evaluator] = {"first": first, "second": second}
    scores = asyncio.run(grade_trial(run, example, registry=registry)).get("results", [])

    assert [(item.key, item.score) for item in scores] == [("first", 1.0), ("second", None)]
    assert scores[1].comment == "评分器执行失败"


def test_exact_match_and_async_judge_receive_same_original_text() -> None:
    """保留换行的严格评分和显式注入的模型评委可同时打分。"""
    run = sample_run("hello\n")
    example = Example(id=uuid4(), inputs={"instruction": "say hello"}, outputs={"answer": "hello"},
                      metadata={"task_id": "hello", "evaluators": ["exact_match", "llm_correctness"]})
    seen: list[tuple[str, str, str]] = []

    async def judge(instruction: str, answer: str, expected: str) -> bool:
        """独立假评委忽略末尾换行，验证收到的原始数据。"""
        seen.append((instruction, answer, expected))
        return answer.rstrip("\n") == expected

    assert "llm_correctness" not in get_evaluators()
    result = asyncio.run(grade_trial(run, example, registry=get_evaluators(judge=judge)))
    assert [(item.key, item.score) for item in result.get("results", [])] == [("exact_match", 0.0), ("llm_correctness", 1.0)]
    assert seen == [("say hello", "hello\n", "hello")]


def test_missing_answer_is_not_graded_as_a_mismatch() -> None:
    """没有实际回答时，反馈为缺分而不是 0 分。"""
    example = Example(id=uuid4(), outputs={"answer": "hello"}, metadata={"evaluators": ["exact_match"]})
    [grade] = asyncio.run(grade_trial(sample_run(None), example)).get("results", [])
    assert grade.key == "exact_match"
    assert grade.score is None

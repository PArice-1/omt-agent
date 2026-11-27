"""验证按 suite 加载任务及幂等注册的公开接口。"""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from langsmith import Client
from langsmith.schemas import Dataset, Example, ExampleCreate
from langsmith.utils import LangSmithAuthError, LangSmithNotFoundError

from tasks import Task, load_tasks, register_dataset


def test_load_tasks_groups_by_directory(tmp_path: Path) -> None:
    """同一 ID 可出现在不同 suite，加载结果按 suite 和文件名稳定排序。"""
    for suite, filename, task_id in [("knowledge_base", "b", "query"), ("file_operations", "z", "query"),
                                      ("file_operations", "a", "read")]:
        directory = tmp_path / suite
        directory.mkdir(exist_ok=True)
        task = {"id": task_id, "instruction": "读取示例", "expected_output": "内容\n",
                "evaluators": ["exact_match"]}
        payload = [task, {**task, "id": "compare", "evaluators": ["exact_match", "contains_expected"]}] if filename == "a" else task
        _ = (directory / f"{filename}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    groups = load_tasks(tmp_path)
    assert list(groups) == ["file_operations", "knowledge_base"]
    assert [task.id for task in groups["file_operations"]] == ["read", "compare", "query"]
    assert groups["file_operations"][1].evaluators == ["exact_match", "contains_expected"]
    assert groups["knowledge_base"][0].expected_output == "内容\n"
    assert list(load_tasks(tmp_path, suite="knowledge_base")) == ["knowledge_base"]


def test_register_reuses_dataset_and_only_appends_new_tasks() -> None:
    """本地 Task.id 是同一 Dataset 下的稳定键，重跑不会重复注册。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    registered: list[Example] = []

    def list_examples(**_kwargs: object) -> Iterator[Example]:
        """返回此前注册的样例，模拟重复执行时读取现有数据。"""
        return iter(registered)

    def add_examples(*, examples: list[ExampleCreate], **_kwargs: object) -> None:
        """将写入替身的样例保存到内存，下次查询可读回。"""
        for example in examples:
            registered.append(Example(
                id=uuid4(), dataset_id=dataset.id, inputs=example.inputs,
                outputs=example.reference_outputs, metadata=example.metadata,
            ))

    hello = Task(id="hello", instruction="输出 hello", expected_output="hello", evaluators=["exact_match"])
    bye = Task(id="bye", instruction="输出 bye", expected_output="bye\n", evaluators=["contains_expected"])
    with (
        patch.object(Client, "read_dataset", side_effect=[LangSmithNotFoundError("not found"), dataset, dataset]),
        patch.object(Client, "create_dataset", return_value=dataset) as create,
        patch.object(Client, "list_examples", side_effect=list_examples),
        patch.object(Client, "create_examples", side_effect=add_examples),
    ):
        first = register_dataset(client, "smoke", [hello])
        second = register_dataset(client, "smoke", [hello, bye])
        third = register_dataset(client, "smoke", [hello, bye])

    assert [item.dataset_id for item in (first, second, third)] == [dataset.id] * 3
    assert [(item.added, item.skipped) for item in (first, second, third)] == [(1, 0), (1, 1), (0, 2)]
    assert [item.inputs for item in registered] == [{"instruction": "输出 hello"}, {"instruction": "输出 bye"}]
    assert [item.outputs for item in registered] == [{"answer": "hello"}, {"answer": "bye\n"}]
    assert [item.metadata for item in registered] == [
        {"task_id": "hello", "evaluators": ["exact_match"]},
        {"task_id": "bye", "evaluators": ["contains_expected"]},
    ]
    create.assert_called_once_with("omt-smoke")


def test_changed_task_does_not_replace_cloud_baseline() -> None:
    """同 ID 内容冲突时，在本 suite 的任何写入前失败。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    existing = Example(
        id=uuid4(), dataset_id=dataset.id, inputs={"instruction": "输出 hello"},
        outputs={"answer": "hello"}, metadata={"task_id": "hello"},
    )
    incoming = [Task(id="new", instruction="输出 new", expected_output="new", evaluators=["exact_match"]),
                Task(id="hello", instruction="输出 hello", expected_output="hello\n", evaluators=["exact_match"])]

    with (
        patch.object(Client, "read_dataset", return_value=dataset),
        patch.object(Client, "list_examples", return_value=iter([existing])),
        patch.object(Client, "create_examples") as write,
        pytest.raises(ValueError, match="hello.*不一致"),
    ):
        _ = register_dataset(client, "smoke", incoming)

    write.assert_not_called()
    assert existing.outputs == {"answer": "hello"}


def test_register_does_not_treat_auth_failure_as_missing_dataset() -> None:
    """鉴权错误不是数据集不存在，不能尝试创建。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    task = Task(id="a", instruction="示例", expected_output="a", evaluators=["exact_match"])
    with (
        patch.object(Client, "read_dataset", side_effect=LangSmithAuthError("not authorized")),
        patch.object(Client, "create_dataset") as create,
        pytest.raises(LangSmithAuthError, match="not authorized"),
    ):
        _ = register_dataset(client, "smoke", [task])
    create.assert_not_called()


def test_duplicate_ids_fail_before_any_registration() -> None:
    """同 suite 不能含两个相同 ID，即便两条任务文本完全相同。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    task = Task(id="hello", instruction="输出 hello", expected_output="hello", evaluators=["exact_match"])
    with (
        patch.object(Client, "read_dataset") as read,
        pytest.raises(ValueError, match="ID 重复：hello"),
    ):
        _ = register_dataset(client, "smoke", [task, task])
    read.assert_not_called()


def test_legacy_example_updates_only_evaluators_with_explicit_flag() -> None:
    """显式迁移旧样例时只补评分配置，不创建重复样例、不改其他元数据。"""
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    dataset = Dataset(id=uuid4(), name="omt-smoke", created_at="2025-01-01T00:00:00Z")
    existing = Example(
        id=uuid4(), dataset_id=dataset.id, inputs={"instruction": "输出 hello"},
        outputs={"answer": "hello"}, metadata={"task_id": "hello", "external": "keep"},
    )
    task = Task(id="hello", instruction="输出 hello", expected_output="hello", evaluators=["exact_match"])
    with (
        patch.object(Client, "read_dataset", return_value=dataset),
        patch.object(Client, "list_examples", return_value=[existing]),
        patch.object(Client, "create_examples") as create,
        patch.object(Client, "update_example") as update,
    ):
        with pytest.raises(ValueError, match="--update-evaluators"):
            _ = register_dataset(client, "smoke", [task])
        update.assert_not_called()
        result = register_dataset(client, "smoke", [task], update_evaluators=True)
        assert (result.added, result.skipped, result.updated) == (0, 0, 1)
        update.assert_called_once_with(
            existing.id, metadata={"task_id": "hello", "external": "keep", "evaluators": ["exact_match"]},
        )
        create.assert_not_called()

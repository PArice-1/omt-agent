from pathlib import Path

import pytest

from tasks import Task, load_task_file


def test_task_file_not_found(tmp_path: Path) -> None:
    """任务文件不存在时，报告明确的文件缺失异常。"""
    file = tmp_path / "hello.txt"

    with pytest.raises(FileNotFoundError, match="文件地址不存在"):
        _ = load_task_file(file)


def test_task_type_error(tmp_path: Path) -> None:
    """传入目录而非普通文件时，拒绝加载。"""
    with pytest.raises(TypeError, match="需要文件地址"):
        _ = load_task_file(tmp_path)


@pytest.mark.parametrize("array", [False, True])
def test_task_load_task(tmp_path: Path, array: bool) -> None:
    """单个对象与单元素数组具有相同的解析结果。"""
    file = tmp_path / "task.json"

    task_json = """
        {
        "id": "hello",
        "instruction": "输出一个hello",
        "expected_output": "hello",
        "evaluators": ["exact_match"]
    }
    """

    expected_task = Task(
        id="hello",
        instruction="输出一个hello",
        expected_output="hello",
        evaluators=["exact_match"],
    )

    _ = file.write_text(f"[{task_json}]" if array else task_json, encoding="utf-8")

    assert load_task_file(file) == [expected_task]


@pytest.mark.parametrize("content", [
    "[]",
    '{"id":"hello","instruction":"hello","expected_output":"hello"}',
    '{"id":"hello","instruction":"hello","expected_output":"hello","evaluators":["a","a"]}',
])
def test_invalid_task_payload_reports_file(tmp_path: Path, content: str) -> None:
    """空数组、缺评分器和重复评分器均在读取时拒绝。"""
    file = tmp_path / "bad.json"
    _ = file.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="任务文件无效.*bad.json"):
        _ = load_task_file(file)

"""串联注册命令与评测入口，只有 LangSmith 存储和 OMT 请求使用替身。"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from langsmith import Client
from langsmith.schemas import Dataset, Example, ExampleCreate
from langsmith.utils import LangSmithNotFoundError

import main as cli
import register_datasets


def test_register_then_run_and_report_by_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """先注册云端样例再执行；报告只含实验索引和均值，不覆盖已有文件。"""
    logged_in = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    datasets: dict[str, Dataset] = {}
    stored: dict[UUID, list[Example]] = {}
    calls: list[tuple[str, str, float]] = []

    def offline_client(**_kwargs: object) -> Client:
        """固定 SDK 运行环境，避免读取工作区配置。"""
        return logged_in

    def read_dataset(_client: Client, *, dataset_name: str) -> Dataset:
        """在内存中模拟 LangSmith 的 Dataset 查询。"""
        if dataset_name not in datasets:
            raise LangSmithNotFoundError("test Dataset not found")
        return datasets[dataset_name]

    def create_dataset(_client: Client, name: str) -> Dataset:
        """创建具备真实 SDK 类型和稳定 ID 的测试 Dataset。"""
        dataset = Dataset(id=uuid4(), name=name, created_at="2025-01-01T00:00:00Z")
        datasets[name] = dataset
        stored[dataset.id] = []
        return dataset

    def list_examples(_client: Client, *, dataset_id: UUID) -> Iterator[Example]:
        """读回注册脚本真正写入的样例。"""
        return iter(stored[dataset_id])

    def create_examples(_client: Client, *, dataset_id: UUID, examples: list[ExampleCreate]) -> None:
        """模拟服务将 reference_outputs 持久化为 Example.outputs。"""
        for item in examples:
            stored[dataset_id].append(Example(id=uuid4(), dataset_id=dataset_id, inputs=item.inputs,
                                             outputs=item.reference_outputs, metadata=item.metadata))

    async def fake_omt(instruction: str, *, base_url: str, timeout: float) -> str:
        """接收 OMT 选项，不联网；严格匹配不通过也仍是有效 trial。"""
        calls.append((instruction, base_url, timeout))
        return "hello\n"

    monkeypatch.setattr(register_datasets, "Client", offline_client)
    monkeypatch.setattr(cli, "Client", offline_client)
    monkeypatch.setattr(Client, "read_dataset", read_dataset)
    monkeypatch.setattr(Client, "create_dataset", create_dataset)
    monkeypatch.setattr(Client, "list_examples", list_examples)
    monkeypatch.setattr(Client, "create_examples", create_examples)
    monkeypatch.setattr(cli, "run_omt", fake_omt)

    assert register_datasets.main(["--suite", "smoke"]) == 0
    assert register_datasets.main(["--suite", "smoke"]) == 0
    report = tmp_path / "reports" / "run.json"
    args = ["--live", "--suite", "smoke", "--no-upload", "--trials", "2",
            "--base-url", "http://127.0.0.1:9001", "--timeout", "2.5", "--report", str(report)]
    assert cli.main(args) == 0
    content = report.read_text(encoding="utf-8")
    assert cli.main(args) == 1

    assert list(datasets) == ["omt-smoke"]
    [example] = stored[datasets["omt-smoke"].id]
    assert example.outputs == {"answer": "hello"}
    assert example.metadata == {"task_id": "hello", "evaluators": ["exact_match"]}
    assert calls == [("请只输出 hello, 不要添加其他文字", "http://127.0.0.1:9001", 2.5)] * 2
    assert report.read_text(encoding="utf-8") == content
    saved = cast(dict[str, dict[str, object]], json.loads(content))
    assert list(saved) == ["smoke"]
    assert saved["smoke"]["dataset_name"] == "omt-smoke"
    assert saved["smoke"]["trial_count"] == 2
    assert saved["smoke"]["experiment_url"] is None
    assert saved["smoke"]["mean_scores"] == {"exact_match": 0.0}
    assert "instruction" not in content
    terminal = capsys.readouterr()
    assert "复用 1" in terminal.out
    assert "报告路径已存在" in terminal.err


def test_main_requires_explicit_live_option() -> None:
    """没有 --live 时拒绝执行。"""
    with pytest.raises(SystemExit) as exc_info:
        _ = cli.main([])
    assert exc_info.value.code == 2

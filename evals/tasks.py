"""读取本地任务和 suite 配置，显式同步 LangSmith Dataset。"""

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar
from uuid import UUID

from langsmith import Client
from langsmith.schemas import Example, ExampleCreate
from langsmith.utils import LangSmithNotFoundError
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter


TASKS_DIR = Path(__file__).resolve().parent / "tasks"


def _unique_evaluators(names: list[str]) -> list[str]:
    """拒绝空白或重复的评分键，保留配置的评分顺序。"""
    if any(not name or name.strip() != name for name in names) or len(names) != len(set(names)):
        raise ValueError("evaluators 必须是互不重复的非空名称，不能有首尾空白")
    return names


type EvaluatorNames = Annotated[list[str], Field(min_length=1), AfterValidator(_unique_evaluators)]


class Task(BaseModel):
    """单条任务；id 在 suite 内唯一，evaluators 为本任务按顺序选用的评分器名称。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^\S+$")
    instruction: str = Field(min_length=1)
    expected_output: str
    evaluators: EvaluatorNames


# Pydantic 在运行时支持 Annotated 联合，TypeForm 尚未识别这类表达式。
_TASK_FILE = TypeAdapter[list[Task] | Task](
    Annotated[list[Task], Field(min_length=1)] | Task,  # pyright: ignore[reportArgumentType]
)


class SuiteConfig(BaseModel):
    """suite.toml 可选，只配置对整次实验执行的汇总评分器。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    summary_evaluators: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RegistrationResult:
    """一次 suite 注册的 Dataset 及新增、复用和仅更新评分配置的样例数。"""

    dataset_name: str
    dataset_id: UUID
    added: int
    skipped: int
    updated: int


def dataset_name(suite: str) -> str:
    """从稳定的 suite 目录名生成 LangSmith Dataset 名，禁止路径成分。"""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", suite):
        raise ValueError(f"无效的 suite 名：{suite!r}（须以小写字母开头，仅允许小写字母、数字、_ 和 -）")
    return f"omt-{suite}"


def load_task_file(path: Path | str) -> list[Task]:
    """读取一个 UTF-8 JSON；接受单个对象或非空数组，统一返回任务列表。"""
    file = Path(path).expanduser()
    if not file.exists():
        raise FileNotFoundError(f"文件地址不存在：{file}")
    if not file.is_file():
        raise TypeError(f"需要文件地址：{file}")
    try:
        parsed = _TASK_FILE.validate_json(file.read_bytes())
        return [parsed] if isinstance(parsed, Task) else parsed
    except ValueError as exc:
        raise ValueError(f"任务文件无效：{file}\n{exc}") from exc


def load_tasks(root: Path | str = TASKS_DIR, *, suite: str | None = None) -> dict[str, list[Task]]:
    """按直接子目录加载任务；默认全选，按目录名和文件名排序，不访问网络。"""
    directory = Path(root).expanduser()
    if suite is not None:
        _ = dataset_name(suite)
        suites = [directory / suite]
    else:
        suites = sorted(path for path in directory.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not suites:
        raise ValueError(f"没有任务 suite：{directory}")

    groups: dict[str, list[Task]] = {}
    for path in suites:
        if not path.is_dir():
            raise ValueError(f"未找到 suite：{path}")
        _ = dataset_name(path.name)
        tasks = [task for file in sorted(path.glob("*.json")) for task in load_task_file(file)]
        _validate_task_ids(path.name, tasks)
        groups[path.name] = tasks
    return groups


def load_suite_config(suite: str, root: Path | str = TASKS_DIR) -> SuiteConfig:
    """读取 suite.toml 的汇总配置；文件不存在时不执行汇总评分器。"""
    _ = dataset_name(suite)
    path = Path(root).expanduser() / suite / "suite.toml"
    try:
        with path.open("rb") as file:
            return SuiteConfig.model_validate(tomllib.load(file))
    except FileNotFoundError:
        return SuiteConfig()
    except ValueError as exc:
        raise ValueError(f"suite 配置无效：{path}\n{exc}") from exc


def _validate_task_ids(suite: str, tasks: Sequence[Task]) -> None:
    """拒绝空 suite 或重复本地 ID，防止注册缺失或覆盖错误的样例。"""
    if not tasks:
        raise ValueError(f"suite {suite!r} 没有 JSON 任务")
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise ValueError(f"suite {suite!r} 的任务 ID 重复：{task.id}")
        seen.add(task.id)


def register_dataset(
    client: Client, suite: str, tasks: Sequence[Task], *, update_evaluators: bool = False,
) -> RegistrationResult:
    """顺序注册一个 suite，复用同名 Dataset，按稳定的 Task.id 去重。

    默认不改既有样例；update_evaluators 只允许更新已匹配指令和参考答案的
    metadata.evaluators，包括为旧样例补字段，不修改其他元数据或样例内容。
    当前 suite 的冲突在任何样例写入前检查；多次云端写入不保证原子性。
    """
    name = dataset_name(suite)
    _validate_task_ids(suite, tasks)
    try:
        dataset = client.read_dataset(dataset_name=name)
    except LangSmithNotFoundError:
        # SDK 的可选 metadata 字典未完整标注；本模块不传入该参数。
        dataset = client.create_dataset(name)  # pyright: ignore[reportUnknownMemberType]

    existing: dict[str, Example] = {}
    for example in client.list_examples(dataset_id=dataset.id):  # pyright: ignore[reportUnknownMemberType]
        task_id: object = (example.metadata or {}).get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"Dataset {name!r} 的样例缺少 metadata.task_id，无法安全去重")
        if task_id in existing:
            raise ValueError(f"Dataset {name!r} 的 task_id 重复：{task_id}")
        existing[task_id] = example

    pending: list[ExampleCreate] = []
    updates: list[tuple[UUID, dict[str, object]]] = []
    for task in tasks:
        inputs = {"instruction": task.instruction}
        reference = {"answer": task.expected_output}
        metadata = {"task_id": task.id, "evaluators": task.evaluators}
        if (example := existing.get(task.id)) is None:
            pending.append(ExampleCreate(inputs=inputs, reference_outputs=reference, metadata=metadata))
            continue
        if example.inputs != inputs or example.outputs != reference:
            raise ValueError(f"Dataset {name!r} 的任务 {task.id!r} 与本地内容不一致；未覆盖云端样例")
        remote_metadata: dict[str, object] = example.metadata or {}
        if remote_metadata.get("evaluators") != task.evaluators:
            if not update_evaluators:
                raise ValueError(f"任务 {task.id!r} 的云端 evaluators 不一致；确认后使用 --update-evaluators")
            updates.append((example.id, {**remote_metadata, "evaluators": task.evaluators}))

    if pending:
        _ = client.create_examples(dataset_id=dataset.id, examples=pending)  # pyright: ignore[reportUnknownMemberType]
    for example_id, metadata_update in updates:
        _ = client.update_example(example_id, metadata=metadata_update)  # pyright: ignore[reportUnknownMemberType]
    return RegistrationResult(name, dataset.id, len(pending), len(tasks) - len(pending) - len(updates), len(updates))

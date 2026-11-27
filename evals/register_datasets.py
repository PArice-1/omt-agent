"""显式将本地 suite 注册到 LangSmith；不启动 OMT，也不执行评测。"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from langsmith import Client
from langsmith.utils import LangSmithError

from tasks import TASKS_DIR, load_tasks, register_dataset


class _Arguments(argparse.Namespace):
    """注册范围：未指定 suite 时注册任务根目录下的全部 suite。"""

    tasks_dir: Path = TASKS_DIR
    suite: str | None = None
    update_evaluators: bool = False


def main(argv: Sequence[str] | None = None) -> int:
    """顺序注册各 suite；仅显式选择时更新评分配置，失败返回 1。"""
    parser = argparse.ArgumentParser(description="向 LangSmith 注册 OMT 评测 Dataset")
    _ = parser.add_argument("--tasks-dir", type=Path, help="本地任务根目录，默认 evals/tasks")
    _ = parser.add_argument("--suite", help="只注册指定 suite，省略时注册全部")
    _ = parser.add_argument("--update-evaluators", action="store_true", help="仅更新匹配样例的评分配置")
    args = parser.parse_args(argv, namespace=_Arguments())

    try:
        groups = load_tasks(args.tasks_dir, suite=args.suite)
        client = Client(auto_batch_tracing=False)
        for suite, tasks in groups.items():
            result = register_dataset(client, suite, tasks, update_evaluators=args.update_evaluators)
            print(f"[{suite}] {result.dataset_name}：新增 {result.added}，复用 {result.skipped}，更新评分 {result.updated}")
    except (LangSmithError, OSError, TypeError, ValueError) as exc:
        print(f"注册失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

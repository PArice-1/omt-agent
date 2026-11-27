"""运行指定 suite 的 LangSmith Experiment，并按 suite 展示评测结果入口。"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from functools import partial
from pathlib import Path

from langsmith import Client
from langsmith.utils import LangSmithError

from harness import SuiteResult, run_suites
from omt_adapter import run_omt
from tasks import TASKS_DIR, load_suite_config, load_tasks


class _Arguments(argparse.Namespace):
    """评测配置：默认选全部 suite，每条样例执行一次，并向 LangSmith 上传结果。"""

    tasks_dir: Path = TASKS_DIR
    suite: str | None = None
    base_url: str = "http://127.0.0.1:8000"
    timeout: float = 60.0
    trials: int = 1
    max_concurrency: int = 1
    report: Path | None = None
    no_upload: bool = False


def _parse_args(argv: Sequence[str] | None) -> _Arguments:
    """解析入口参数；--live 是允许发送模型及工具请求的显式确认。"""
    parser = argparse.ArgumentParser(description="使用 LangSmith 运行 OMT 评测 suite")
    _ = parser.add_argument("--live", action="store_true", required=True, help="确认调用真实 OMT API")
    _ = parser.add_argument("--tasks-dir", type=Path, help="本地任务根目录，默认 evals/tasks")
    _ = parser.add_argument("--suite", help="只跑指定 suite，省略时运行全部")
    _ = parser.add_argument("--base-url", help="OMT API 根地址，默认 http://127.0.0.1:8000")
    _ = parser.add_argument("--timeout", type=float, help="单次 HTTP 阻塞操作超时（秒），默认 60")
    _ = parser.add_argument("--trials", type=int, help="每条样例的重复次数，默认 1")
    _ = parser.add_argument("--max-concurrency", type=int, help="同时运行的 trial 上限，默认 1")
    _ = parser.add_argument("--report", type=Path, help="可选的本地 JSON 实验索引路径，不覆盖已有文件")
    _ = parser.add_argument("--no-upload", action="store_true", help="读取远端 Dataset，但不上传评测运行")
    return parser.parse_args(argv, namespace=_Arguments())


def _write_report(path: Path, reports: dict[str, SuiteResult]) -> None:
    """写入按 suite 名分组的实验索引和分数均值，不写提示和模型原文。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump({suite: asdict(result) for suite, result in reports.items()}, file, ensure_ascii=False, indent=2)
        _ = file.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并启动异步评测；未显式传入 --live 不执行任务。"""
    return asyncio.run(_run(_parse_args(argv)))


async def _run(args: _Arguments) -> int:
    """运行已注册的 suite；低分不算运行错误，执行或评分缺失返回 1。"""
    try:
        report_path = args.report.expanduser() if args.report is not None else None
        if report_path is not None and report_path.exists():
            raise ValueError(f"报告路径已存在：{report_path}")
        groups = load_tasks(args.tasks_dir, suite=args.suite)
        suites = {suite: load_suite_config(suite, args.tasks_dir) for suite in groups}
        client = Client(auto_batch_tracing=not args.no_upload)
        agent = partial(run_omt, base_url=args.base_url, timeout=args.timeout)
        reports = await run_suites(
            suites, client, agent, trials=args.trials,
            max_concurrency=args.max_concurrency, upload_runs=not args.no_upload,
        )
        if not args.no_upload:
            await asyncio.to_thread(client.flush)
        for suite, result in reports.items():
            counts = f"{result.failed_trials} 个运行失败，{result.unscored_trials} 个评分缺失"
            print(f"[{suite}] {result.experiment_name}：{result.trial_count} 次 trial，{counts}")
            if result.mean_scores:
                averages = "，".join(f"{name}={score:g}" for name, score in result.mean_scores.items())
                print(f"  平均分：{averages}")
            if result.experiment_url:
                print(f"  {result.experiment_url}")
        if report_path is not None:
            _write_report(report_path, reports)
            print(f"报告：{report_path}")
    except (LangSmithError, OSError, TypeError, ValueError) as exc:
        print(f"评测失败：{exc}", file=sys.stderr)
        return 1
    return int(any(result.failed_trials or result.unscored_trials for result in reports.values()))


if __name__ == "__main__":
    raise SystemExit(main())

# 使用 LangSmith 评测 OMT

`evals/` 是独立的 uv 项目，不安装或部署 OMT。评测进程从 LangSmith 取样例，通过 OMT 非流式 HTTP 运行 Agent；LangSmith 负责重复执行、评分和记录 Experiment。

## 注册并运行

先准备 LangSmith 工作区和 `LANGSMITH_API_KEY`（通过环境变量提供，不写入 Git）。使用已配置且可信的本机 [OMT API](omt/api.md)，为评测实例使用独立的 `OMT_API_DB_PATH` 和工作目录。新会话只隔离对话历史，不隔离工具对文件或外部系统的访问。

从仓库根目录执行；示例的评测 API 监听 8001：

```bash
cd evals
uv sync --frozen
uv run --frozen python register_datasets.py --suite smoke
uv run --frozen python main.py --live --suite smoke --base-url http://127.0.0.1:8001 --report output/smoke.json
```

- 注册和评测是两个显式步骤。新增任务先注册；只改 Agent 或评分器实现时可以直接重跑。已注册样例的评分器名单变动（或旧样例还没有名单）时，用 `register_datasets.py --suite <suite> --update-evaluators` 显式更新。
- 两个命令都支持 `--suite` 选一个 suite，省略时按名称顺序处理全部；`--tasks-dir` 可覆盖任务根目录。评测默认连接 `http://127.0.0.1:8000`，通过 `--trials` 设置每条样例的重复次数（默认 1），通过 `--timeout` 设置 OMT HTTP 阻塞操作超时（默认 60 秒）。
- 每个 suite 用一次 `aevaluate()` 生成一个 Experiment，suite 之间顺序执行。`--max-concurrency` 限制同一 suite 内同时运行的 trial 数，默认 1，不能超过评测 API 的 `OMT_API_MAX_CONCURRENT_RUNS`。例如要并发 4 个 trial，先用 `OMT_API_MAX_CONCURRENT_RUNS=4` 启动评测 API，再传 `--max-concurrency 4`。会修改同一文件或其他共享资源的任务，在隔离工作区之前请保持并发 1。
- 在 LangSmith 打开 `omt-smoke` 等 Dataset，可以查看每条样例、评分并对比历次实验。`--report` 可额外写按 suite 分组的 JSON，包含实验名称和链接、运行失败数、评分缺失数和逐条评分均值，不覆盖已有文件。均值只统计已有数值分数，不把运行失败当成 0 分。任务判分不通过不算命令执行失败。
- `--no-upload` 仍从 LangSmith 读取已注册的 Dataset，但不向 LangSmith 上传本次 Experiment；不会关闭 OMT 后端独立配置的 tracing。注册会上传任务指令和参考答案，评测默认还会上传实际回答；只使用允许上传的数据。当前适配器只返回最终回答，不采集会话 transcript。

## 添加一个 suite

在 `evals/tasks/` 下创建小写名称子目录，例如 `file_operations/` 或 `knowledge_base/`。任务文件是 UTF-8 JSON，可以是单个任务对象，也可以是包含一个或多个任务的数组。每条任务含 `id`、`instruction`、`expected_output` 和非空、无重复的 `evaluators` 列表。ID 在 suite 内唯一（包括跨文件和数组内），注册后应保持稳定。

```json
[
  {"id": "hello", "instruction": "请只输出 hello", "expected_output": "hello", "evaluators": ["exact_match"]},
  {"id": "pong", "instruction": "回复中包含 pong", "expected_output": "pong", "evaluators": ["exact_match", "contains_expected"]}
]
```

逐条评分器只由任务 JSON 决定。[`suite.toml`](../evals/tasks/smoke/suite.toml) 可选，只配置 `summary_evaluators`。

| 模块 | 职责 |
| --- | --- |
| [`tasks.py`](../evals/tasks.py) | 用 Pydantic 校验任务，`load_tasks()` 返回按 suite 名分组的 `dict[str, list[Task]]`（不联网），`register_dataset()` 写入远端 Dataset。 |
| [`graders/graders.py`](../evals/graders/graders.py) | 集中维护逐条和汇总评分器字典。`grade_trial(run, example)` 从 Example 取逐条评分器名单，用 `asyncio.TaskGroup` 并发评分。每项都收到同一个 Run 和 Example；单项报错保留其他分数，不伪造零分。 |
| [`harness/`](../evals/harness/) | 预检所有已注册样例的评分器名单，按 suite 调用 `Client.aevaluate()`。每个 trial 只通过异步 [`omt_adapter`](../evals/omt_adapter.py) 发一次任务指令；参考答案只用于评分。 |

内置逐条评分器有 `exact_match` 和 `contains_expected`；`llm_correctness` 仅在程序调用 harness 时显式注入独立的异步 `judge` 才可用。汇总评分器 `completion_rate` 统计无运行错误的 trial 比例，不是答对率。

一个 suite 对应一个 `omt-<suite>` Dataset。注册用 `metadata.task_id` 去重，并把评分器名单写到 `metadata.evaluators`。新 ID 追加，完全一致就跳过；同 ID 的指令或参考答案不同，或云端 ID 重复或缺失时停止该 suite 的写入。只有传入 `--update-evaluators` 才会更新已有样例的评分名单，不修改指令、参考答案或其他元数据。不自动删除旧样例，评测以远端样例为准。注册单独顺序执行，不支持并发同步。

## 离线验证

```bash
cd evals
uv run --frozen --no-sync python -m pytest tests -q
```

测试使用内存存储和 HTTP 替身，数据库、模型和云端 Dataset 不会被读写。见 [脚本测试说明](tests/scripts.md#omt-评测注册与执行入口)。

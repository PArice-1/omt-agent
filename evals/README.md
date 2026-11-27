# OMT Agent 评测

本项目使用 LangSmith，按 suite 注册 Dataset、异步运行 Experiment。每条任务在 JSON 里选择评分器。完整使用说明、任务格式和离线验证命令见 [OMT 评测文档](../docs/evals.md)。

`python register_datasets.py --help` 和 `python main.py --help` 可查看两种入口的参数。注册命令会访问 LangSmith；实际调用 OMT 需显式传入 `--live`。

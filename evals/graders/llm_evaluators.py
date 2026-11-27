"""依赖调用方显式提供的独立异步模型评委，不绑定厂商。"""

from collections.abc import Awaitable, Callable

from langsmith.evaluation import EvaluationResult
from langsmith.schemas import Example, Run

from .code_evaluators import answer_pair


# 评委依次接收原始指令、实际回答、参考答案，异步返回是否通过。
type LLMJudge = Callable[[str, str, str], Awaitable[bool]]


def make_llm_correctness(judge: LLMJudge) -> Callable[[Run, Example], Awaitable[EvaluationResult]]:
    """将独立模型评委适配为逐条评分器；创建时不请求模型。"""

    async def llm_correctness(run: Run, example: Example) -> EvaluationResult:
        """从 Example 和 Run 提取评委所需的原始数据。"""
        instruction: object = (example.inputs or {}).get("instruction")
        if not isinstance(instruction, str):
            raise ValueError("llm_correctness 要求字符串 instruction")
        answer, expected = answer_pair(run, example)
        return EvaluationResult(key="llm_correctness", score=float(await judge(instruction, answer, expected)))

    return llm_correctness

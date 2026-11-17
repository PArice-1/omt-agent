"""共用 SDK 元数据替身；只有显式申请的测试使用，不污染真实 SDK 能力专项。"""

from collections.abc import Callable

import pytest

from omt.ai import litellm_backend


@pytest.fixture
def sdk_reasoning(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str, tuple[str, ...] | None], None]:
    """向 SDK 本地表注入测试模型；None 表示推理已知但等级未知，空元组表示不支持。

    声明只在当前用例生效，不读取模型目录、不请求网络，也不改写真实 SDK 安装文件。
    上层流程测试据此控制模型能力，不再把旧 thinkingLevelMap 当成能力来源。
    """
    def install(provider: str, model: str, efforts: tuple[str, ...] | None) -> None:
        # 对真实协议用例保留 SDK 的价格/上下文等字段，避免测试能力替身破坏后台计费日志。
        existing: dict[str, object] = (litellm_backend.litellm.model_cost.get(f"{provider}/{model}")
                                       or litellm_backend.litellm.model_cost.get(model) or {})
        entry: dict[str, object] = {
            **existing, "litellm_provider": provider, "mode": "chat", "supports_reasoning": efforts != (),
        }
        for name in tuple(entry):
            if name == "reasoning_effort_levels" or (name.startswith("supports_") and name.endswith("_reasoning_effort")):
                _ = entry.pop(name)
        if efforts is not None:
            entry["reasoning_effort_levels"] = list(efforts)
        monkeypatch.setitem(litellm_backend.litellm.model_cost, f"{provider}/{model}", entry)
    return install

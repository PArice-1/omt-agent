"""模型门面：隐藏 LiteLLM 构造细节，向 Agent 提供 BaseChatModel。"""

from langchain_core.language_models import BaseChatModel
from pydantic import HttpUrl

from .models_manager import models_provider


class Model:
    """立即构造所选模型；不读取配置、不请求目录或试运行模型。

    provider/model/base_url 来自上层已校验的选择，kwargs 为凭据和 SDK 调用选项。
    model 属性始终是可交给 Agent 的聊天模型，不再临时保存模型 ID 字符串。
    """

    def __init__(self, provider: str, *, model: str, base_url: HttpUrl, **kwargs: object) -> None:
        self.provider: str = provider
        self.base_url: HttpUrl = base_url
        self.model: BaseChatModel = self._init_model(provider, model=model, base_url=base_url, args=kwargs)

    def _init_model(
        self, provider: str, *, model: str, base_url: HttpUrl, args: dict[str, object],
    ) -> BaseChatModel:
        """通过统一注册入口构造模型，失败继续传播，不返回伪模型。"""
        return models_provider(provider, model=model, base_url=base_url, args=args)

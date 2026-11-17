"""读取 agent/ 下的设置、认证和模型目录；不在这里创建模型或刷新认证。"""

from functools import cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings

from omt.ai.litellm_backend import get_model_capabilities

root = Path("~/.omt").expanduser().resolve()
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    """模型选择配置，对应 agent/settings.json。"""

    defaultProvider: NonEmptyString = Field(description="默认模型提供商")
    defaultModel: NonEmptyString = Field(description="默认模型标识，与模型目录中的 id 一致")
    defaultThinkingLevel: NonEmptyString | None = Field(
        default=None,
        description="可选思考等级；未配置时按 none 回退，其他等级必须由 LiteLLM 声明支持",
    )


class AuthCredential(BaseModel):
    """保留认证类型和 API Key；其他认证字段不会被误作 API Key 或打印。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    type: NonEmptyString
    key: SecretStr | None = None


class ModelDefinition(BaseModel):
    """模型连接定义；旧 thinkingLevelMap 及其他元数据不再参与能力解析。"""

    id: NonEmptyString
    baseUrl: HttpUrl
    provider: NonEmptyString | None = None

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        """从 SDK 本地数据派生等级；不联网、不修改模型目录或猜造未知能力。

        目录解析会补齐缺失的 provider；独立且未标明厂商的定义只提供 none 回退项。
        """
        return get_model_capabilities(provider=self.provider or "", model=self.id).available_levels


class ProviderModels(BaseModel):
    """同一提供商下的模型定义。"""

    models: list[ModelDefinition]

    @model_validator(mode="after")
    def _check_unique_model_ids(self) -> Self:
        ids = [model.id for model in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("同一提供商下的模型 id 不得重复")
        return self


_AUTH_ADAPTER = TypeAdapter(
    dict[str, AuthCredential], config=ConfigDict(hide_input_in_errors=True)
)
_MODEL_STORE_ADAPTER = TypeAdapter(
    dict[str, ProviderModels], config=ConfigDict(hide_input_in_errors=True)
)


def _bind_provider_names(catalog: dict[str, ProviderModels]) -> dict[str, ProviderModels]:
    """给目录中省略厂商的模型绑定外层名称；保留显式不匹配值供原有校验拒绝。"""
    return {provider: ProviderModels(models=[
        model.model_copy(update={"provider": provider}) if model.provider is None else model
        for model in group.models
    ]) for provider, group in catalog.items()}


def parse_model_store(document: object) -> dict[str, ProviderModels]:
    """校验内存目录并绑定所属厂商；与磁盘读取共用同一规则，不请求 SDK 目录或写入。"""
    return _bind_provider_names(_MODEL_STORE_ADAPTER.validate_python(document))


@cache
def load_settings() -> Settings:
    """读取并缓存模型选择；保留 cache_clear() 以便调用者主动重载。"""
    settings_path = root / "agent" / "settings.json"
    return Settings.model_validate_json(settings_path.read_text(encoding="utf-8"))


def load_auth() -> dict[str, AuthCredential]:
    """读取最新认证，不缓存密钥，不在错误消息中包含文件原文或凭据。"""
    path = root / "agent" / "auth.json"
    content = path.read_text(encoding="utf-8")
    try:
        return _AUTH_ADAPTER.validate_json(content)
    except ValidationError:
        raise ValueError(
            f"认证配置文件 {path} 格式无效，请检查 JSON 语法和各提供商的 type/key 字段"
        ) from None


def load_model_store() -> dict[str, ProviderModels]:
    """读取最新模型目录，校验 HTTP(S) 地址及同一提供商下的模型 ID 唯一性。"""
    path = root / "agent" / "model-store.json"
    content = path.read_text(encoding="utf-8")
    try:
        return _bind_provider_names(_MODEL_STORE_ADAPTER.validate_json(content))
    except ValidationError:
        raise ValueError(
            f"模型目录 {path} 格式无效，请检查 JSON、models 列表、唯一 id 和 baseUrl 地址"
        ) from None

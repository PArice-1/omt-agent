"""CLI 启动配置，与 HTTP 使用相同会话字段，但不需要访问令牌。"""

from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from omt.core.configuration import McpServerSettings, SessionSettings, StdioServerSettings


def _default_mcp_servers() -> dict[str, McpServerSettings]:
    """本机测试用的默认 knowledge 服务；仅 CLI/TUI 使用，环境变量可覆盖或以 {} 关闭。"""
    # 临时测试配置：更换服务目录时修改这里；启动运行环境时才会连接服务。
    root = Path("/home/laterain/Projects/Agent/rag-mcp")
    db_root = Path("/home/laterain/.omt")
    return {
       "knowledge": StdioServerSettings(
           transport="stdio",
           command=str(root / ".venv" / "bin" / "python"),
           args=[
               "-m", "rag_mcp.mcp.server",
               "--build-on-start",
               "--source", str(db_root / "knowledge-database"),
               "--db-path", str(db_root / "knowledge-database" / "storage"),
               "--collection", "knowledge",
           ],
           cwd=str(root),
       )
   }

class CliSettings(SessionSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="OMT_CLI_", frozen=True, extra="forbid", hide_input_in_errors=True,
    )
    skill_roots: list[Path] | None = Field(default=[Path("~/.agents/skills").expanduser().resolve()])
    mcp_servers: dict[str, McpServerSettings] = Field(default_factory=_default_mcp_servers)

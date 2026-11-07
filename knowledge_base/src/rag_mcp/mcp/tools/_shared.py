"""工具公共的 JSON 序列化和只读声明。"""

import json
from typing import Any

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)

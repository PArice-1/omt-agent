"""本地持久化 RAG 知识库与 MCP 工具。"""


def main() -> None:
    from .mcp.server import main as serve

    serve()

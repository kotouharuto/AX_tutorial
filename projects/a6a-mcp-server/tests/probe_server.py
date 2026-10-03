"""テスト専用：例外の種類で Claude に届く内容がどう変わるかを確かめるサーバ。

本番のサーバに「わざと壊れるツール」を入れないため、別ファイルにしている。
"""

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer("probe")


@server.tool()
def raise_tool_error() -> str:
    """ToolError を投げる（想定済みの失敗）。"""
    raise ToolError("設定が足りない：A6A_CORPUS_DIR を設定すること")


@server.tool()
def raise_value_error() -> str:
    """ValueError を投げる（v1 の感覚で書いた場合）。"""
    raise ValueError("設定が足りない：A6A_CORPUS_DIR を設定すること")


if __name__ == "__main__":
    server.run(transport="stdio")

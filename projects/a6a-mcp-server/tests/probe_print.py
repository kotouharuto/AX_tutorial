"""観察用：stdio サーバで print() すると何が起きるか。

PRINT_AT で print する場所を切り替える。
  startup  起動時（server.run の前）
  tool        ツール呼び出しの中（改行あり）
  tool_noeol  ツール呼び出しの中（改行なし）
  none        print しない（比較用）
"""

import os

from mcp.server import MCPServer

server = MCPServer("print-probe")
WHERE = os.environ.get("PRINT_AT", "none")

if WHERE == "startup":
    print("サーバを起動します")  # 素朴なデバッグ出力


@server.tool()
def hello(name: str) -> str:
    """挨拶を返す。"""
    if WHERE == "tool":
        print(f"hello が呼ばれた: {name}")  # 素朴なデバッグ出力
    if WHERE == "tool_noeol":
        # 改行なし。直後に書かれる JSON 応答と**同じ行**に混ざる
        print(f"hello が呼ばれた: {name}", end="", flush=True)
    return f"こんにちは、{name}"


if __name__ == "__main__":
    server.run(transport="stdio")

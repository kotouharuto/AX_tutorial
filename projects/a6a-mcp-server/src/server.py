"""A-6a の MCP サーバー。stdio で動く。

【stdio サーバの絶対の制約】**標準出力に何も書かない。**
標準出力は JSON-RPC の通信路そのもので、`print()` を1行入れるだけで通信が壊れる。
ログは `logging`（既定で標準エラー出力）に出す。

【エラーの返し方（SDK v2）】利用者に説明させたい失敗は **`ToolError` で投げる。**
それ以外の例外は「想定外のクラッシュ」として扱われ、Claude には
`Error executing tool <名前>` としか届かない（原因のメッセージは隠される）。
v1 の感覚で `ValueError` を投げると、Claude が原因を説明できなくなる。
"""

import logging
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from search import CorpusError, Index, load_corpus

# 標準エラー出力に出す。**標準出力に向けない。**
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("a6a")

CORPUS_ENV = "A6A_CORPUS_DIR"
MAX_TOP_K = 10

server = MCPServer(
    name="a6a-internal-docs",
    instructions=(
        "社内規程・業務手順の文書を検索するツールを提供する。"
        "回答には必ず出典（文書名）を添えること。"
        "検索結果に答えが無い場合は、無いと答え、推測で補わないこと。"
    ),
)

# インデックスは最初の呼び出し時に作る（下記 _get_index 参照）
_index: Index | None = None


def _get_index() -> Index:
    """インデックスを返す。未作成なら作る。

    【起動時ではなく呼び出し時に作る理由】起動時に失敗すると、クライアントには
    「サーバに接続できない」としか出ず、利用者は原因に辿り着けない。
    呼び出し時なら ToolError として Claude に原因が届き、説明できる。
    """
    global _index
    if _index is not None:
        return _index

    raw = os.environ.get(CORPUS_ENV, "").strip()
    if not raw:
        raise ToolError(
            f"文書フォルダが設定されていない。環境変数 {CORPUS_ENV} に、"
            "検索対象の文書（.md / .txt）が入ったフォルダの絶対パスを設定する必要がある。"
            "Claude Code なら `claude mcp add` の `--env`、Claude Desktop なら設定ファイルの "
            "`env` に書く。"
        )

    try:
        chunks, skipped = load_corpus(Path(raw).expanduser())
    except CorpusError as exc:
        # 想定済みの失敗なので ToolError に変換し、原因を Claude に届ける
        raise ToolError(f"{exc}。環境変数 {CORPUS_ENV} の値を確認すること。") from exc

    logger.info("インデックス作成：%d チャンク（対象外 %d ファイル）", len(chunks), len(skipped))
    _index = Index(chunks)
    return _index


@server.tool()
def search_documents(query: str, top_k: int = 5) -> str:
    """社内規程・業務手順の文書を検索し、該当箇所を出典付きで返す。

    Args:
        query: 探したい内容（例：「経費精算の締め日」「備品の購入手順」）
        top_k: 返す件数（1〜10）
    """
    if not query.strip():
        raise ToolError("検索語が空。探したい内容を文章か単語で指定すること。")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ToolError(f"top_k は 1〜{MAX_TOP_K} で指定すること（指定値: {top_k}）。")

    hits = _get_index().search(query, top_k)
    logger.info("検索：%d 件ヒット", len(hits))  # 検索語そのものはログに残さない

    if not hits:
        # 0件は異常ではなく「該当なし」。Claude が推測で補わないよう明示する。
        return (
            f"「{query}」に該当する文書は見つからなかった。"
            "文書に記載が無い可能性がある。推測で回答しないこと。"
        )

    lines = [f"「{query}」の検索結果：{len(hits)} 件"]
    for rank, hit in enumerate(hits, 1):
        lines.append(f"\n[{rank}] 出典：{hit.doc_name}（スコア {hit.score:.2f}）\n{hit.text}")
    return "\n".join(lines)


def main() -> None:
    """stdio で起動する。"""
    logger.info("起動：%s", server.name)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

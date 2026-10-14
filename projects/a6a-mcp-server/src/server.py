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
from sheet import MAX_LIMIT as SHEET_MAX_LIMIT
from sheet import SheetError, fetch_inquiries

# 標準エラー出力に出す。**標準出力に向けない。**
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("a6a")

CORPUS_ENV = "A6A_CORPUS_DIR"
SHEET_URL_ENV = "A6A_SHEET_API_URL"
# 認証情報。**コードにも設定例にも値を書かない。** 環境変数からのみ読む
SHEET_TOKEN_ENV = "A6A_SHEET_API_TOKEN"
MAX_TOP_K = 10

server = MCPServer(
    name="a6a-internal-docs",
    instructions=(
        "社内規程・業務手順の文書の検索と、問い合わせ記録の参照を提供する。"
        "回答には必ず出典（文書名）を添えること。"
        "検索結果に答えが無い場合は、無いと答え、推測で補わないこと。"
        "問い合わせ記録は、氏名・メールアドレス・担当者の列を除き、値の中のメールアドレスと"
        "本人の氏名も伏せて返す。ただし本文に書かれた第三者の氏名などは伏せきれないことがあるので、"
        "個人情報が含まれていないと断定しないこと。"
        "[想定外の値] や [列ずれのため非表示]、警告が付いた行は、元のシートの列がずれている。"
        "目印の位置から元のデータを推測して説明しないこと（目印は伏せた結果であり、事実ではない）。"
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


@server.tool()
def list_inquiries(
    status: str | None = None, category: str | None = None, limit: int = 20
) -> str:
    """問い合わせ記録を新しい順に返す。

    氏名・メールアドレス・担当者の列は返さない。値の中のメールアドレスと本人の氏名は
    [メールアドレス]・[氏名] に置き換えて返す。ただし伏せきれないことがある。

    状態の意味：
      完了   = 分類し、担当者に振り分けた
      未分類 = 分類はしたが担当者マスタに該当が無く、予備の宛先に送った（意図した動作）
      エラー = 分類の処理に失敗した（詳細に理由がある）

    [想定外の値]・[列ずれのため非表示]・「注意」が付いた行は、元のシートの列がずれている。
    列ずれした行は内容と詳細を返さない（どこに個人情報が入っているか分からないため）。

    Args:
        status: 状態で絞り込む（「完了」「未分類」「エラー」のいずれか。省略時はすべて）
        category: 分類で絞り込む（「システム障害」「申請手続き」「備品・設備」「その他」。省略時はすべて）
        limit: 返す件数（1〜50）
    """
    if not 1 <= limit <= SHEET_MAX_LIMIT:
        raise ToolError(f"limit は 1〜{SHEET_MAX_LIMIT} で指定すること（指定値: {limit}）。")

    url = os.environ.get(SHEET_URL_ENV, "").strip()
    token = os.environ.get(SHEET_TOKEN_ENV, "").strip()
    missing = [name for name, value in ((SHEET_URL_ENV, url), (SHEET_TOKEN_ENV, token)) if not value]
    if missing:
        raise ToolError(
            f"問い合わせ記録の接続先が設定されていない（未設定: {', '.join(missing)}）。"
            "GAS のウェブアプリの URL とトークンを、Claude Code なら `claude mcp add` の `-e`、"
            "Claude Desktop なら設定ファイルの `env` に設定する必要がある。"
        )

    try:
        result = fetch_inquiries(url, token, status=status, category=category, limit=limit)
    except SheetError as exc:
        # SheetError の文言にはトークンを含めていない（sheet.py 側で保証）
        raise ToolError(str(exc)) from exc

    # 件数だけ記録する。問い合わせ内容は個人情報を含みうるのでログに出さない
    logger.info("問い合わせ記録：%d 件中 %d 件を返した", result.total, len(result.rows))

    condition = "・".join(
        f"{label}={value}" for label, value in (("状態", status), ("分類", category)) if value
    ) or "条件なし"
    if not result.rows:
        return f"問い合わせ記録（{condition}）に該当するものは無かった。"

    lines = [f"問い合わせ記録（{condition}）：{result.total} 件中 {len(result.rows)} 件（新しい順）"]
    for row in result.rows:
        lines.append(
            f"\n- {row.get('timestamp', '')}｜分類：{row.get('category', '')}｜"
            f"緊急度：{row.get('urgency', '')}｜状態：{row.get('status', '')}\n"
            f"  内容：{row.get('content', '')}"
        )
        if row.get("detail"):
            lines.append(f"  詳細：{row['detail']}")
        if row.get("warnings"):
            lines.append(f"  注意：{'／'.join(row['warnings'])}")
    return "\n".join(lines)


def main() -> None:
    """stdio で起動する。"""
    logger.info("起動：%s", server.name)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

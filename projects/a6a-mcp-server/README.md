# A-6a：MCP サーバー

社内文書の検索と、問い合わせ記録シートの参照を、MCP のツールとして公開する。
Claude Code と Claude Desktop の両方から使う。

## 公式ドキュメントとの照合（実装前に実施）

**照合日：2026-10-03**

方針書の指示：「SDK と各クライアントの設定方法は変更が速い。実装前に公式ドキュメントで
現行の書き方を確認し、確認した URL と日付を README に残すこと。」

### バージョン（照合時点）

| 対象 | バージョン |
|---|---|
| MCP Python SDK（PyPI 最新） | **2.3.0** |
| MCP 仕様（公式ドキュメントの版） | 2026-07-28 |
| Claude Code（検証環境） | 2.1.231 |
| Claude Desktop（検証環境） | 2.19675.0 |

A-6b で、**公式ドキュメントは最新版の挙動を書いており、古いバージョンでは
挙動が違う箇所があった**。そのため照合時点のバージョンと検証環境のバージョンを両方残す。

### 参照した URL

| 内容 | URL |
|---|---|
| Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| サーバの作り方（ロギング・Claude Desktop の設定） | https://modelcontextprotocol.io/docs/develop/build-server |
| Claude Code の MCP 設定 | https://code.claude.com/docs/en/mcp |
| PyPI | https://pypi.org/project/mcp/ |

### 私の認識と違った点

**1. SDK が v2 になり、クラス名が変わった**

| | 私の認識（v1） | 現行（v2） |
|---|---|---|
| import | `from mcp.server.fastmcp import FastMCP` | **`from mcp.server import MCPServer`** |

移行ガイドが出ている破壊的変更。**v1 の書き方の記事・回答が大量に残っている**ので、
検索して出てきたコードをそのまま使うと動かない可能性がある。
→ `pyproject.toml` で `mcp>=2.3,<3` と上限を付けた。

**2. Claude Desktop の設定例がそのままでは動かない可能性がある**

公式の例は `"command": "uv"`。注記で「**uv のフルパスが必要な場合がある**」とだけある。

Claude Desktop は GUI アプリなので、A-5a の launchd と同じく `~/.zshrc` を読まず、
`~/.local/bin`（uv の場所）が PATH に入っていない可能性が高い。

→ **予測として記録し、先回りせず公式例どおりに書いて確認する。**

### 照合で確認した仕様（実装が依存する部分）

**stdio のサーバでは stdout に書き込まない。**

> Writing to stdout will corrupt the JSON-RPC messages and break your server.
> The `print()` function writes to stdout by default, so keep it out of a STDIO server entirely.

標準ライブラリの `logging`（既定で stderr に出る）を使う。

**Claude Desktop の設定ファイル**（macOS）：
`~/Library/Application Support/Claude/claude_desktop_config.json`
の `mcpServers` に書く。パスは**絶対パス**。

## 設計の判断

| 判断 | 選んだもの | 理由 |
|---|---|---|
| 検索方式 | **BM25 のみ**（文字 bi-gram） | 埋め込み（torch・仮想環境 1.7GB）は stdio サーバの起動が重い。A-6a の目的は MCP の配線で、検索精度は深追いしない |
| シートの読み方 | **GAS をウェブアプリ化**し、トークン付きで取得 | 設定が軽く A-1 の資産を活かせる。トークンは環境変数 |
| 他プロジェクトの資産 | **import しない**。コーパスは環境変数でパスを指定 | 各 `projects/*` は独立して動かす規約。複製もしない |

BM25 単独の検索精度は A-2 で測っていない（A-2 で測ったのは vector と hybrid）。
**精度が下がっている可能性がある**ことは前提として扱う。

## 実装中に分かったこと

### 例外の種類で、Claude に届く内容が変わる（SDK v2）

| 投げた例外 | Claude が受け取る本文 |
|---|---|
| `ToolError("原因")` | `Error executing tool X: 原因` |
| **それ以外の例外**（`ValueError` など） | `Error executing tool X`（**原因が消える**） |

SDK のソースにこう書かれている。

> Any other exception … is treated as a crash: the model sees only `Error executing tool <name>`

**v1 の感覚で `ValueError("CORPUS_DIR が未設定")` と書くと、Claude は利用者に
原因を説明できない。** 到達条件「失敗時に Claude が理解して説明できるエラーを返す」を
静かに満たさなくなる。`tests/test_stdio.py` でプロトコル越しに両方を固定した。

`ToolError` は `mcp.server.mcpserver.exceptions` にある（`mcp.server` からは import できない）。

### 環境変数は親から子に渡らない

SDK の stdio クライアントは、親の環境変数を **HOME・LOGNAME・PATH・SHELL・TERM・USER の6つしか**
子プロセスに渡さない。**シェルで `export` しただけの変数はサーバから見えない。**
クライアントの設定（`env`）に明示する必要がある。

### インデックスは起動時ではなく、最初の呼び出し時に作る

起動時に作ると、`A6A_CORPUS_DIR` の設定ミスで**サーバ自体が起動に失敗**し、
クライアントには「接続できない」としか出ない。
呼び出し時なら `ToolError` として原因が Claude に届き、利用者に説明できる。

### 「該当なし」と「文書が1件もない」を区別する

前者は正常（`is_error=False`・推測で答えないよう明示）、後者は設定ミス（`is_error=True`）。
A-5a の「0件を成功扱いしない」と同じ考え方。

## 観察：stdio サーバで print() すると何が起きるか

方針書の観察対象。公式ドキュメントは「stdout に書くとサーバが壊れる」と書いている。

**SDK 2.3.0（サーバ・Python クライアント）では、素朴な print() で呼び出しは壊れなかった。**

| ケース | 出力先 | 呼び出し |
|---|---|---|
| 起動時に print | **通信路**（退避の前なので） | 成功 |
| ツール内で print（改行あり） | **通信路**（バッファに残り、終了時に fd が戻ってから出た） | 成功 |
| ツール内で print（`flush=True`） | **stderr**（退避が効いた） | 成功 |

壊れなかった理由は二重の防御。

1. **サーバ側**：起動時に stdout（fd 1）を退避し、fd 1 に stderr をつなぎ直す
   （`mcp/server/stdio.py` の `_claim_fd`）
2. **クライアント側**：JSON として読めない行は `Failed to parse JSONRPC message from server`
   を stderr に出して**捨てる**

### それでも print しない

- 起動時とバッファ経由では、**実際に通信路へ不正な行が流れている**。
  壊れなかったのはこの Python クライアントが寛容だから
- **Claude Code と Claude Desktop は別実装のクライアント。** 同じく寛容とは限らない
  → 実際のクライアントでの挙動は接続時に確認する
- **壊れないので、入っても気づけない。** 動作確認では見つからないため、
  `tests/test_no_stdout.py` で本番コードに `print` が無いことを静的に検査している

観察に使ったスクリプト：`tests/probe_print.py`、`tests/observe_print.py`

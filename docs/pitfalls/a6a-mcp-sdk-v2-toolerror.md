# MCP SDK v2 では、ToolError 以外の例外の原因が Claude に届かない

- **ブロック：** A-6a
- **日付：** 2026-10-03
- **一般性：** 同じ構成なら誰でも（MCP Python SDK 2.x）
- **溶かした時間：** 約 0.5 時間

## 現象

ツールの中で、設定ミスを説明するつもりで例外を投げた。

```python
raise ValueError("CORPUS_DIR が設定されていない")
```

Claude が受け取った本文はこれだけだった。

```
Error executing tool search_documents
```

**原因（CORPUS_DIR が未設定）が消えている。** Claude は利用者に「ツールの実行に失敗しました」としか言えない。

あわせて、v1 の書き方は**import の時点で落ちる**。

```python
from mcp.server.fastmcp import FastMCP   # → ModuleNotFoundError（SDK 2.3.0）
```

## 再現手順

1. `mcp>=2.3` を入れ、`MCPServer` でツールを作る
2. ツールの中で `ValueError("原因")` を投げる
3. stdio でクライアントから呼ぶ → 本文が `Error executing tool <名前>` だけになる
4. 同じ場所で `ToolError("原因")` を投げる → `Error executing tool <名前>: 原因` と原因が付く

## 原因

SDK v2 は、例外を「想定済みの失敗」と「想定外のクラッシュ」に分けて扱う。SDK のソースの記述：

> Any other exception … is treated as a crash: the model sees only `Error executing tool <name>`

`ToolError`（`mcp.server.mcpserver.exceptions`）だけが、メッセージを Claude に渡す。
それ以外の例外は、内部情報の漏洩を防ぐためにメッセージを隠し、サーバのログにだけ残す。

**v1（`FastMCP`）の感覚で普通の例外を投げると、静かに原因が消える。** エラーにはなるので、
「エラー処理は書いた」と思い込んだまま、利用者に説明できない状態が残る。

## 対処

説明させたい失敗は `ToolError` で投げる。下位の処理は独自の例外にし、ツールの境目で変換する。

```python
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

try:
    chunks, skipped = load_corpus(Path(raw))
except CorpusError as exc:
    raise ToolError(f"{exc}。環境変数 A6A_CORPUS_DIR の値を確認すること。") from exc
```

**区別のしかた**（テストで確かめるとき）：接頭辞 `Error executing tool X` は `ToolError` でも付く。
**コロンの後ろに原因が続くか**で見分ける。当初「接頭辞があればクラッシュ扱い」と思い込んで書いたテストが外れた。

```python
assert body != "Error executing tool search_documents"   # クラッシュ扱いなら本文はこれだけ
assert "A6A_CORPUS_DIR" in body                          # 原因が届いている
```

**プロトコル越しに確かめる。** サーバ側の `call_tool()` を直接呼ぶテストだけでは、
Claude が実際に何を受け取るかは分からない。別プロセスで起動し、SDK のクライアントで呼ぶ。

### あわせて踏んだこと

- **クライアントは親の環境変数を6つしか子に渡さない**（HOME・LOGNAME・PATH・SHELL・TERM・USER）。
  シェルで `export` しただけの値はサーバから見えない。クライアントの設定（`env`）に明示する
- **重い初期化は起動時ではなく、最初の呼び出し時に行う。** 起動時に失敗すると、クライアントには
  「接続できない」としか出ず、原因が `ToolError` として届かない。Claude Desktop は約3秒で3回起動していた

## 効かなかった対処

- **ネットの記事のコードをそのまま使う。** v1（`FastMCP`）向けが大量に残っており、1行目で落ちる。
  `pyproject.toml` に `mcp>=2.3,<3` と上限を付け、v3 の破壊的変更を勝手に取り込まないようにした

## 他人の環境に納品するときの含意

- **エラーの文言は、Claude を経由して利用者に届く「説明書」になる。** 何を設定すれば直るか
  （環境変数名・設定場所）まで書く。実クライアントで、Claude が原因を読んで取り直すことを確認した
- **SDK のメジャーバージョンを記録する。** 照合した日付とバージョンを README に残した（`mcp 2.3.0`）

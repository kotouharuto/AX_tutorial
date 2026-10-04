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

## クライアントへの接続（2026-10-04〜05）

### 接続の結果

| クライアント | 登録先 | 確認したこと |
|---|---|---|
| Claude Code（ターミナル） | `~/.claude.json`（`claude mcp add`・local スコープ） | 正常系・**異常系で Claude が原因を説明**できた |
| Claude Code（Desktop のコードタブ） | 同上 | 正常系 |
| Claude Desktop（チャット） | `claude_desktop_config.json` | 正常系・設定画面で実行中を確認 |

**Claude Code と Claude Desktop は MCP の設定を共有しない。** 同じサーバを両方で使うには、
それぞれに登録する必要がある。

異常系（`top_k=50`）で Claude Code が受け取った本文：

```
Error executing tool search_documents:
top_k は 1〜10 で指定すること（指定値: 50）。
```

Claude はこれを読み、上限の10で再実行するかを提案した。
プロトコル越しのテストで固定した「`ToolError` なら原因が届く」が、実クライアントでも成り立った。

### 予測が外れた：Claude Desktop は uv を見つけた

公式例どおり `"command": "uv"` で書いた。**A-5a の launchd と同じく、GUI アプリは
`~/.zshrc` を読まないので uv が見つからないと予測したが、起動に成功した。**

```
Using MCP server command: /Users/haruto/.local/bin/uv with path: { paths: [ ...14個... ] }
Server started and connected successfully
```

**Desktop は PATH を独自に組み立てていた**（`~/.local/bin`、nodenv、pyenv、nvm、Homebrew を含む14個）。
launchd の経験を Desktop に当てはめただけで、根拠が足りなかった。

公式ドキュメントの「uv のフルパスが必要な場合がある」は、この PATH に含まれない場所に
uv を入れた環境で起きると考えられる（未確認）。

### ログから分かったこと

- **サーバは約3秒の間に3回起動された**（起動 → 意図的な終了 → 再起動）。
  起動処理の重さが3倍効く。埋め込みを使わず BM25 にしたこと、
  インデックスを呼び出し時に作ることが効いている
- サーバが `logging` で stderr に出したログが、**Desktop のログファイルにそのまま残る**
  （`~/Library/Logs/Claude/mcp-server-a6a-docs.log`）。利用者が後から確認できる

### 実クライアントでの print の扱い

起動時に print するサーバ（`tests/probe_print.py`・`PRINT_AT=startup`）を Claude Code に登録し、
`claude mcp list` で **✔ Connected** になった。Claude Code のクライアントも、
Python クライアントと同じく起動時の不正な行に寛容だった。
（`Connected` は起動と初期化が通ったことまで。ツール呼び出し中の print は実クライアントでは未確認）

### auto モードでは MCP ツールが確認なしで動く

Claude Code で検索ツールを呼んだとき、**使用許可を求められなかった。**
ユーザー設定が `defaultMode: auto` だったため。公式ドキュメントの判定順序：

1. allow / ask / deny のルールに一致すれば、それに従う
2. 読み取りと作業ディレクトリ内の編集は自動承認
3. **それ以外は分類器（別のモデル）が判定する** ← MCP ツールはここ

**書き込み・削除・外部送信をするツールでも、分類器が通せば確認なしで実行される。**
サーバ側で必ず確認させるには、ツールの `_meta` に `anthropic/requiresUserInteraction` を付ける
（allow ルールに一致しても、auto モードでも、利用者に確認を求める）。
`readOnlyHint` などのアノテーションを分類器が参照するかは、ドキュメントに記述が無かった。

| ツールの性質 | 推奨 |
|---|---|
| 読み取りのみ | 付けない |
| 書き込み・削除・外部送信 | **`requiresUserInteraction` を付ける** |

参照：https://code.claude.com/docs/en/permission-modes （2026-10-04 照合）

## ツール2：問い合わせ記録の参照（`list_inquiries`）

A-1 の問い合わせ記録シートを、**スタンドアロンの GAS をウェブアプリとして公開**して読む。
GAS のコードは `gas/`、デプロイ手順は `gas/DEPLOY.md`（Google アカウントでの操作のためユーザーが行う）。

### 設計の判断

| 判断 | 選んだもの | 理由 |
|---|---|---|
| GAS の置き場所 | **A-6a 側に独立して作る** | 完了済みの A-1 を変更しない。`clasp push` は全ファイルを送るため、A-1 に足すとエディタ側の変更を上書きしうる |
| トークンの渡し方 | **POST の本文** | GAS のウェブアプリは**HTTP ヘッダを受け取れない**（公式ドキュメントで確認）。URL のクエリはアクセスログや履歴に残る |
| 返す列 | **個人を特定できる列を除く** | お名前・メールアドレス・担当者（メールアドレス）は返さない。列の選択は GAS 側で固定し、Python 側の誤りで漏れないようにした |
| スコープ | `spreadsheets.readonly` のみ | 読むだけなので。A-1 で「スコープを足すと承認がやり直し」を踏んでいる |

### GAS 側の仕様による制約

- **ステータスコードは常に 200**（ContentService では変えられない）。
  成否は本文の `ok` で判定する。ステータスだけ見ると、失敗も成功に見える
- POST すると **302 で別の URL にリダイレクト**され、そこから GET で応答を受け取る。
  Python の `urllib` は 302 で POST を GET に切り替えて辿るので、そのまま動く（偽の GAS で確認）
- **トークン未設定のときは必ず拒否する。** 書き忘れると「設定なし（undefined）」と
  「送られてこない（undefined）」が一致し、誰でも読める状態になる

### テスト

手元に**偽の GAS**（`http.server`）を立て、本物と同じく POST → 302 → GET の経路で確かめた。

- トークンが本文で送られ、**URL に載らない**
- **200 で HTML が返っても成功扱いしない**（公開範囲の設定ミスでログイン画面が返る状況を想定）
- 失敗時のメッセージに**トークンが含まれない**

## 既知の制約：文書が少ないと、該当があっても0件になる

テストを書いていて見つけた。**2文書のコーパスで「経費精算」と検索すると0件になる。**

| 文書数 | 「経費」の idf | 該当文書のスコア |
|---|---|---|
| **2** | **0.000** | **0（該当なし）** |
| 3 | 0.511 | 1.23 |
| 5 | 1.099 | 2.27 |

BM25（Okapi）の idf は `log((N - n + 0.5) / (n + 0.5))` で、**半数の文書に出る語で 0 になる。**
スコアが 0 の文書は返さない作りなので「該当なし」になり、Claude は「記載が無い」と答える。
**静かに誤る型。**

代替の BM25Plus は無関係な文書にも正のスコアを付けるため、「スコア 0 なら該当なし」の
判定が使えなくなる。直すには判定方法ごと設計し直す必要があり、**検索精度のチューニングは
A-6a の目的外なので方式は変えない。** テストで制約として固定した。

実際のコーパス（60文書・数百チャンク）では起きない。
**文書が数件しかないなら、そもそも検索せず全文を渡せばよい**（A-2 の「作らない方が精度が高い」と同じ結論）。

## テストの状況

43件。カバレッジ 94%（`search.py` 100% / `server.py` 92% / `sheet.py` 88%）。

stdio のテストは別プロセスでサーバを起動するのでカバレッジが追えない。
同じ処理をプロセス内で呼ぶテストを別に置いている（`tests/test_search.py`）。

# クライアントの設定ファイルを手で編集すると、黙って壊れる（全角スペース・キー名）

- **ブロック：** A-6a
- **日付：** 2026-10-14〜15
- **一般性：** どの環境でも（特に日本語入力を使う環境）
- **溶かした時間：** 約 0.5 時間

## 現象

MCP サーバの接続先（URL とトークン）を Claude Desktop の設定ファイル
（`~/Library/Application Support/Claude/claude_desktop_config.json`）に手で追記した。
Claude Code では動いたが、Desktop では2つの壊れ方が同時に起きていた。

### 1. 全角スペースで JSON が読めない

```
Expecting property name enclosed in double quotes: line 22 column 38
```

22行目は見た目に異常が無い。文字コードを調べると、**カンマの直後に全角スペース（U+3000）**が1文字あった。

```
"...": "shared",　   ← U+3000 IDEOGRAPHIC SPACE
```

場所は今回編集した `env` ではなく、アプリ自身が書く `preferences` の中だった。

### 2. キー名の打ち間違いはエラーにならない

```
A6A_SHEETS_API_URL   ← 設定ファイル（S が1文字多い）
A6A_SHEET_API_URL    ← サーバが探す名前
```

JSON としては正しいので何も起きず、サーバは「接続先が未設定」として扱う。

## 再現手順

1. 日本語入力を有効にしたまま、JSON ファイルの空白を打つ
2. クライアントを再起動 → 設定ファイル全体が読めない（エラー位置は見た目では分からない）
3. 環境変数のキー名を1文字変える → エラーにならず未設定扱いになる

## 原因

- **JSON の空白として許されるのは、半角スペース・タブ・改行だけ。** 全角スペースは見た目で区別できない
- **設定ファイルは「余分なキー」を拒まない。** 打ち間違えたキーは単に使われない
- **Claude Code と Claude Desktop は MCP の設定を共有しない。** 片方で動いても、もう片方の設定は検証されていない。
  手順書の確認手順に「Claude Code **または** Desktop で確認」と書いたため（私の誤り）、Desktop 側の確認が抜けていた

## 対処

**値を出さずに設定を検査するスクリプト**で見つけた。秘密の値（トークン）を画面に出さないことが前提。

```python
import json, unicodedata
from pathlib import Path

p = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
text = p.read_text(encoding="utf-8")

# 1) JSON の空白として許されない空白文字を探す
bad = [(i, f"U+{ord(c):04X}") for i, c in enumerate(text) if c.isspace() and c not in " \t\n\r"]
print("許されない空白:", bad)

# 2) 必要なキーが揃っているか・もう一方のクライアントと値が一致するか（値は出さない）
desk = json.loads(text)["mcpServers"]["a6a-docs"]["env"]
code = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
code = code["projects"]["/path/to/project"]["mcpServers"]["a6a-docs"]["env"]
for k in ("A6A_CORPUS_DIR", "A6A_SHEET_API_URL", "A6A_SHEET_API_TOKEN"):
    print(k, "一致" if desk.get(k) and desk.get(k) == code.get(k) else "★不一致または未設定")
```

全角スペースを削除し、キー名を直したあと、Desktop の再起動で動いた。

## 効かなかった対処

- **エラー位置の行を目で見る**：全角スペースは見た目で分からない
- **片方のクライアントで動いたことを根拠にする**：設定ファイルが別なので、何も保証しない

## 他人の環境に納品するときの含意

- **手で JSON を編集させる手順を渡すなら、検査の手段もセットで渡す。** 値を出さずに、
  JSON として読めるか・必要なキーが揃うかを確かめられるようにする
- **日本語環境では全角スペースの混入を最初に疑う。** 日本語入力のまま空白を打つと入る
- **到達条件が「両方で動く」なら、確認手順も両方を必須にする。**「または」と書かない
- 秘密を含む設定ファイルは、**画面共有やチャットに貼らずに検査できる**ことが重要。
  今回、トークンは一度も画面にもチャットにも出していない

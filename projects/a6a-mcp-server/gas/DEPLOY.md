# シート参照 API のデプロイ手順

A-1 の問い合わせ記録シートを、MCP サーバから読めるようにする。
**Google アカウントでの操作が含まれるため、あなたが行う。**

所要時間の目安：20分

---

## 0. 事前に確認すること

```bash
cd /Users/haruto/dev/ax_tutorial/projects/a6a-mcp-server/gas
ls -a
```

`appsscript.json` と `Code.js` があること。

```bash
git status --short .
```

**何も表示されないこと**（未コミットの変更が無い）。
この後の `clasp create` が `appsscript.json` を書き換える可能性があり、
そのとき `git` で元に戻すため。

---

## 1. GAS のプロジェクトを作る（3分）

```bash
clasp create --type standalone --title "a6a-sheet-api"
```

**確認：`appsscript.json` が書き換わっていないか**

```bash
git diff appsscript.json
```

何か表示された場合は元に戻す（新規プロジェクトの既定値で上書きされた状態。
放っておくとタイムゾーンが America/New_York になり、スコープの指定も消える）。

```bash
git checkout -- appsscript.json
```

**確認：clasp が正しいファイルを認識しているか**

```bash
clasp status
```

`appsscript.json` と `Code.js` が並んでいること。
`src/` のような余計な階層が付いていたら止めて連絡する（A-1 で踏んだ二重化）。

> `.clasp.json` が作られるが、`.gitignore` で除外済み。**コミットしない。**

---

## 2. コードを送る（1分）

```bash
clasp push --force
```

`--force` を付けないと、非対話のシェルでは「Skipping push.」と出て**何もせず終了する**
（終了コード0なので成功に見える。A-1 で踏んだ）。

ここで `--force` を付けてよいのは、**作ったばかりのプロジェクトで、
リモートに守るべき変更が無いため。**

---

## 3. スクリプトプロパティを設定する（5分）

エディタを開く。

```bash
clasp open-script
```

### シート ID を調べる

A-1 の問い合わせ記録のスプレッドシートをブラウザで開き、URL から取り出す。

```
https://docs.google.com/spreadsheets/d/【ここがシート ID】/edit
```

### トークンを作る

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

> **このトークンをチャットに貼らないこと。** 漏れた場合は作り直す。

### 設定する（GAS のエディタの中で）

**ここで設定するのは GAS 側だけ。** Claude Code・Claude Desktop の設定や `.env` には入れない。

1. エディタの**左端のアイコン列の歯車**（プロジェクトの設定）を開く
2. **一番下までスクロール**して「スクリプト プロパティ」を探す
3. 「スクリプト プロパティを追加」で2つ追加する

| プロパティ | 値 |
|---|---|
| `SHEET_ID` | 上で調べたシート ID |
| `API_TOKEN` | 上で作ったトークン |

4. **「スクリプト プロパティを保存」を押す。** 押さないと反映されない

画面の文言は Google 側の更新で変わることがある。見当たらなければ止めて連絡する。

**どこに何を設定するか：**

| 値 | GAS のスクリプトプロパティ | Claude 側（手順6） |
|---|---|---|
| シート ID | **ここだけ** | 設定しない |
| トークン | ここ | 同じ値を `A6A_SHEET_API_TOKEN` として |
| ウェブアプリの URL | — | `A6A_SHEET_API_URL` として |

シート ID を使うのは GAS だけ。Claude 側は URL とトークンしか知らない。

**トークンはこの後も使うので、手元に控えておく**（ターミナルに表示されたまま）。

---

## 4. シートの読み取りを承認する（3分）

エディタで `Code.js` を開き、上部の関数の選択が **`authorize`** になっていることを確認して「実行」。

> `authorize` をファイルの先頭に置いているので、既定で選ばれているはず。
> 違う関数が選ばれていると「承認したのに何も起きない」になる（A-1 で踏んだ）。

承認画面が出る。**画面に書かれている内容を読んでから承認する。**

- 要求されているのは「スプレッドシートの**表示**」だけのはず（読み取り専用のスコープに絞っている）
- 「編集」「作成」「削除」が含まれていたら**承認せず止めて連絡する**（スコープの設定が想定と違う）
- **項目ごとのチェックボックスが出たら、すべてにチェックを入れる。**
  外すと、承認は通るのに読み取りで失敗する（A-1 で踏んだ）

**確認：実行ログ**に次のように出ること。

```
承認OK：回答シートの行数 = （数字）
```

`SHEET_ID が設定されていない` と出たら、3 のプロパティ名の綴りを確認する。

### 次のエラーが出た場合

| エラー | 原因と対処 |
|---|---|
| `Specified permissions are not sufficient to call SpreadsheetApp.openById` | **古いコードのまま。** 下の「コードを更新した場合」の手順で送り直す |
| `Sheets API has not been used in project ...` | Sheets API が有効になっていない。エラー文中の URL を開いて「有効にする」を押し、数分待って再実行 |
| `シートを読めない。SHEET_ID が正しいか…` | シート ID の誤りか、シート名が「回答」でない。実行ログ（エディタの「実行数」）に詳細がある |

### コードを更新した場合（送り直し）

`Code.js` や `appsscript.json` を直したときは、送り直してから `authorize` をもう一度実行する。
**スコープや有効にするサービスが変わると、承認画面がもう一度出る。**

```bash
cd /Users/haruto/dev/ax_tutorial/projects/a6a-mcp-server/gas
clasp push --force
```

ブラウザのエディタは**再読み込み**してから `authorize` を実行する（古いコードのまま実行しないため）。

---

## 5. ウェブアプリとして公開する（3分）

エディタ右上の「デプロイ」→「新しいデプロイ」→ 種類の選択（歯車）→「ウェブアプリ」。

| 項目 | 設定 |
|---|---|
| 説明 | `a6a シート参照` |
| 次のユーザーとして実行 | **自分** |
| アクセスできるユーザー | **全員** |

「デプロイ」を押し、表示された **ウェブアプリの URL**（`https://script.google.com/macros/s/.../exec`）を控える。

### 「全員」にする理由と、それで安全な理由

MCP サーバは Google のログインをしないので、「全員」でないと呼べない。
**URL を知っていれば誰でも呼べる状態になるが、トークンが一致しないと何も返さない。**
またトークンが未設定のときは必ず拒否するように書いてある。

返す列は `Code.js` で固定しており、**お名前・メールアドレス・担当者は返さない。**

---

## 6. MCP サーバに接続先を設定する（5分）

### Claude Code

**トークンをコマンドに直接書かない。** シェルの履歴に残るため。変数に読み込んでから使う。

```bash
read -rs A6A_TOKEN
```

（入力しても画面に表示されない。トークンを貼り付けて Enter）

```bash
read -r A6A_URL
```

（ウェブアプリの URL を貼り付けて Enter）

登録し直す（`-e` を足すため、一度削除する）。

```bash
claude mcp remove a6a-docs
```

```bash
claude mcp add a6a-docs -e A6A_CORPUS_DIR=/Users/haruto/dev/ax_tutorial/projects/a2-rag/corpus/out -e A6A_SHEET_API_URL="$A6A_URL" -e A6A_SHEET_API_TOKEN="$A6A_TOKEN" -- uv --directory /Users/haruto/dev/ax_tutorial/projects/a6a-mcp-server run src/server.py
```

履歴に残るのは `"$A6A_TOKEN"` という文字列で、トークンそのものではない。

**確認：**

```bash
claude mcp list
```

`a6a-docs` が `✔ Connected` であること。

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` の
`a6a-docs` の `env` に2行足す。

```json
"env": {
  "A6A_CORPUS_DIR": "/Users/haruto/dev/ax_tutorial/projects/a2-rag/corpus/out",
  "A6A_SHEET_API_URL": "（ウェブアプリの URL）",
  "A6A_SHEET_API_TOKEN": "（トークン）"
}
```

保存したら Claude Desktop を完全に終了（⌘Q）して起動し直す。

> **このファイルにはトークンが平文で保存される。** ファイルの権限は所有者のみ読み書き
> （`-rw-------`）になっているが、バックアップやファイル共有の対象にしないこと。
> サーバ側は環境変数から読んでいるが、**その値をクライアントに渡す設定ファイル自体は秘密を含む。**

---

## 7. 動作を確認する（3分）

新しいセッション（Claude Code）または新しいチャット（Desktop）で聞く。

```
問い合わせ記録のうち、状態が「未分類」のものを見せて
```

| 確認 | 期待 |
|---|---|
| 件数と内容が返る | A-1 のシートの内容と一致する |
| **お名前・メールアドレスが含まれていない** | 返す列を絞っているため |

異常系（Claude が原因を説明できるか）：

```
list_inquiries を limit=100 で呼んで、結果をそのまま教えて
```

「limit は 1〜50」と原因が説明されれば正しい。

---

## （任意）壊れ方の観察：公開範囲を間違えたら何が返るか

方針書の「先に壊して対処を覚える」に沿った観察。時間があれば行う。

5 で「アクセスできるユーザー」を**「自分のみ」**にした別のデプロイを作り、その URL で 7 を試す。

予想：**HTTP 200 でログイン画面（HTML）が返る。** 成功に見えるが中身はデータではない。
MCP サーバは「応答が JSON ではなかった（HTML）」と原因を返すはず。

結果がどうであれ、何が返ったかを教えてほしい（記録する）。

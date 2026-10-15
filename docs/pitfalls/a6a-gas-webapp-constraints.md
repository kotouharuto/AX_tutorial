# GAS ウェブアプリの制約：ヘッダが読めない・常に200・版が固定・SpreadsheetApp は読み取り専用で動かない

- **ブロック：** A-6a
- **日付：** 2026-10-05〜14
- **一般性：** 同じ構成なら誰でも（Apps Script をウェブアプリとして外部から呼ぶ）
- **溶かした時間：** 約 1.0 時間

## 現象

MCP サーバ（Python）から、A-1 のシートを GAS のウェブアプリ経由で読む構成にした。4つの制約を踏んだ。

### 1. `SpreadsheetApp` が読み取り専用のスコープで動かない

最小権限にするつもりで `spreadsheets.readonly` に絞ったら、権限承認の実行で失敗した。

```
Specified permissions are not sufficient to call SpreadsheetApp.openById.
Required permissions: https://www.googleapis.com/auth/spreadsheets
```

### 2. コードを直して `clasp push` しても、公開中の URL は古い動作のまま

エラーは出ない。直したつもりで古い動作が続く。

### 3. HTTP ヘッダを受け取れない／ステータスは常に 200

トークンを `Authorization` ヘッダで渡せない。失敗しても 200 が返る。

## 再現手順

1. スタンドアロンの GAS で `SpreadsheetApp.openById(id)` を書き、マニフェストのスコープを `spreadsheets.readonly` にする
2. エディタから実行 → 上のエラー
3. ウェブアプリとして公開したあとコードを直し `clasp push --force` → 公開 URL の応答は変わらない

## 原因

| 制約 | 仕組み |
|---|---|
| `SpreadsheetApp` と readonly | 公式リファレンスで、`SpreadsheetApp` が受け付けるのは `spreadsheets.currentonly` と `spreadsheets` のみ。**読み取り専用は無い**。`currentonly` は紐付いたシート専用で、ID で別のシートを開く構成では使えない |
| 版の固定 | ウェブアプリは**デプロイした時点の版を固定して配信する**。push は編集中の版（HEAD）を更新するだけ |
| ヘッダ | `doPost(e)` のイベントオブジェクトにヘッダの項目が無い（公式ドキュメントで確認） |
| 常に 200 | `ContentService` ではステータスコードを変えられない |

**1 は私の誤り。** 「読むだけなら readonly で足りる」と確かめずに書き、README と手順書にもそう書いていた。

## 対処

### `SpreadsheetApp` をやめて Sheets API（高度なサービス）で読む

`spreadsheets.values.get` は `spreadsheets.readonly` を受け付ける（公式の API リファレンスで確認）。

```json
"dependencies": {
  "enabledAdvancedServices": [
    { "serviceId": "sheets", "userSymbol": "Sheets", "version": "v4" }
  ]
},
"oauthScopes": ["https://www.googleapis.com/auth/spreadsheets.readonly"]
```

```js
const response = Sheets.Spreadsheets.Values.get(id, "'" + SHEET_NAME + "'");
return response.values || [];  // シートが空なら values が無い
```

**Sheets API は行末の空セルを省略して返す**（`SpreadsheetApp` は省略しない）。
行ごとに長さが違う配列になるので、添字で読むと空欄が `undefined` になる。

```js
function cellAt(row, i) { return i < row.length ? row[i] : ''; }
```

### 公開中の版を更新する

エディタの「デプロイ」→「**デプロイを管理**」→ 編集 → バージョン「**新バージョン**」→ デプロイ。
**URL は変わらない。**「新しいデプロイ」で作り直すと URL が変わり、接続先の設定をやり直すことになる。

### ヘッダと 200

- トークンは **POST の本文**で送る（URL のクエリはアクセスログや履歴に残る）
- 成否は本文の `ok` で判定する。呼び出し側は**ステータスではなく `ok` を見る**
- **サーバ側にトークンが未設定なら必ず拒否する。** 書き忘れると、未設定（undefined）と
  送られてこない（undefined）が一致し、誰でも読める

```js
const expected = PropertiesService.getScriptProperties().getProperty('API_TOKEN');
if (!expected) throw new RequestError('サーバ側でトークンが設定されていない');
if (typeof token !== 'string' || token !== expected) throw new RequestError('認証に失敗した');
```

### GAS は手元で動かせないので、Node で検査する

デプロイしてから論理の誤りが見つかると、push → 承認 → 実行の往復が増える。
`Sheets`・`PropertiesService`・`ContentService` を偽物に差し替えて、Node 上で `doPost` を動かした
（`projects/a6a-mcp-server/tests/gas/run_code.js`・20件）。
**偽物は公式の記述から作ったもので、本物の応答の形までは保証しない。**

## 効かなかった対処

- **スコープを `spreadsheets` に広げる**：動くが採らなかった。「全員」に公開し**所有者の権限で動く入口**が、
  所有者の全シートの編集・削除権限を持つことになる。最小権限が一番効くのがこういう場所
- **`clasp push` だけで直す**：公開中の版は変わらない

## 他人の環境に納品するときの含意

- **ライブラリのスコープは、読み取りでも確かめる。** 「読むだけなら readonly」は成り立たないことがある
- **ウェブアプリの更新手順を引き渡し文書に書く。** push だけでは反映されず、エラーも出ない
- **「全員」に公開する入口は、トークン照合を必ず失敗側に倒す**（未設定なら拒否）
- 手順書には、よく出るエラー文と対処の表を付けた（`projects/a6a-mcp-server/gas/DEPLOY.md`）

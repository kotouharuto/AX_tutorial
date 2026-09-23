# MailApp と GmailApp はスコープが別。診断用の1行でスコープが増える

- **ブロック：** A-1
- **日付：** 2026-08-25
- **一般性：** どの環境でも
- **溶かした時間：** 約 0.1 時間

## 現象

`oauthScopes` に `gmail.send` を宣言し、送信は `GmailApp.sendEmail()` で実装。
動作していたが、診断用関数の実行時に例外。

```
Exception: Specified permissions are not sufficient to call
MailApp.getRemainingDailyQuota.
Required permissions: https://www.googleapis.com/auth/script.send_mail
```

## 原因

**メール送信には API が2系統あり、要求スコープが違う。**

| API | 代表メソッド | 要求スコープ |
|---|---|---|
| `GmailApp` | `sendEmail`, `getInboxThreads` 等 | `gmail.send` / `gmail.readonly` など Gmail 系 |
| `MailApp` | `sendEmail`, `getRemainingDailyQuota` | **`script.send_mail`** |

`MailApp` は「Apps Script として送る」簡易 API、`GmailApp` は Gmail そのものを操作する API。
名前が似ていて用途も重なるため無意識に混ぜやすいが、**混ぜるとスコープが両方必要になる。**

今回は残り送信可能数を出すためだけに `MailApp` を1行使っており、
そのせいで納品先に説明すべきスコープが1つ増えていた。

## 対処

**スコープを足すのではなく、その1行を削除した。**

```js
// 【削除済み】MailApp.getRemainingDailyQuota() はここには書かない。
// MailApp と GmailApp はスコープが別で、前者は script.send_mail を要求する。
// 送信自体は GmailApp（gmail.send）で足りるため、診断のためだけに
// 権限を1つ増やすのは割に合わない。残り送信数は Apps Script のダッシュボードで見る。
```

**判断基準：** そのスコープを納品先に1行で説明できるか。
「残り送信数を画面に出すためです」は、権限を1つ広げる理由として弱い。

## この事象が「見えた」理由（重要）

**`appsscript.json` に `oauthScopes` を明示していたから検知できた。**

明示せず自動推論に任せていた場合、clasp / Apps Script はコードを走査して
`script.send_mail` を**黙って追加する。** 承認画面には
「メールを送信する」権限が増えた状態で表示され、
開発者は増えたことにすら気づかない。納品先で
「なぜこの権限が要るのか」と聞かれて答えられない事態になる。

**最小権限は「書いた方が安全」ではなく「書かないと変化が見えない」。**

## 他人の環境に納品するときの含意

- `oauthScopes` は**必ず手で書く。** 自動推論はスコープを増やす方向にしか働かない。
- ライブラリやユーティリティを1つ足すたびにスコープが増えていないか確認する。
  差分が出たら、その機能が本当に必要かを先に問う。
- 承認画面の文言は開発者ではなく**利用者と情シスが読む。**
  技術的に最小でも、表示上「メールを送信して削除する」のように怖く見える組み合わせがある。
  実際に承認画面を見て確認する。

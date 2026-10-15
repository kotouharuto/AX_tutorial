# A-5b：Slack Bot

Slack のスラッシュコマンド `/inquiry` で問い合わせを受け、A-1 と同じ方法（Gemini）で分類して返す。
分類に応じて担当チャンネルに振り分ける。Socket Mode で動かすので公開 URL は要らない。

## 公式ドキュメントとの照合（実装前に実施）

**照合日：2026-10-16**

| 対象 | バージョン |
|---|---|
| slack-bolt | **1.30.0** |
| slack-sdk | 3.45.0 |
| Gemini のモデル | gemini-3.6-flash（A-1 と同じ） |

| 内容 | URL |
|---|---|
| ack（応答） | https://docs.slack.dev/tools/bolt-python/concepts/acknowledge |
| スラッシュコマンド | https://docs.slack.dev/interactivity/implementing-slash-commands |
| アプリのマニフェスト | https://docs.slack.dev/reference/app-manifest |
| Socket Mode | https://docs.slack.dev/apis/events-api/using-socket-mode |

### 照合で確認した仕様

| 項目 | 内容 |
|---|---|
| 応答期限 | **3秒（3000ミリ秒）**。過ぎると利用者に `operation_timeout` |
| 推奨 | **重い処理の前に、すぐ `ack()` する** |
| 既定の返し方 | `ephemeral`（送った本人にだけ見える）。`in_channel` でチャンネルに出る |
| Socket Mode | 公開 URL 不要。スラッシュコマンドも WebSocket で届く。アプリレベルトークン（`xapp-`）を使う |
| 受領確認をしなかった場合 | Slack は**再送する**（受領確認が再送の判断に使われる） |
| **Socket Mode のアプリはマーケットプレイスに出せない** | 顧客ごとに個別のアプリとトークンが要る |

### ドキュメントで確かめられなかったこと

- **権限（スコープ）を足したとき、再インストールが要るか**。マニフェストのリファレンスに記述が無い。
  方針書の観察対象なので、実際に試して確かめる

インストールした実物で API も確かめた：`App`・`SocketModeHandler`・`@app.command`、
`process_before_response` の既定は `False`。

## 設計の判断

| 判断 | 選んだもの | 理由 |
|---|---|---|
| LLM | **Gemini（A-1 と同じ）** | 「A-1 の分類結果」と比べられる。プロンプト・モデル・温度0を揃えた |
| 送り方 | **スラッシュコマンド** | 応答期限の超過が利用者の画面に `operation_timeout` として出るので観察しやすい |
| アプリの作り方 | **マニフェストから作る** | 要求する権限がファイルに残る。権限を足すときも差分で説明できる |
| 最初の権限 | **`commands` だけ** | 振り分け通知で `chat:write` が要る段で足し、**再インストール前の挙動を観察する** |
| 設定の検査 | `src/settings.py` | 値を出さずに、空・取り違え・空白の混入・キー名の打ち間違いを見つける（A-6a の反省） |

## 構成

```
manifest.yaml      Slack アプリのマニフェスト
.env.example       設定の雛形（.env はコミットしない）
SETUP.md           Slack 側の準備手順（ユーザーが行う）
src/
  settings.py      設定の読み込みと検査（値は出さない）
  classifier.py    分類（Gemini・A-1 と同じプロンプト）
  app.py           Bot 本体
tests/             21件（Slack と Gemini には接続しない）
```

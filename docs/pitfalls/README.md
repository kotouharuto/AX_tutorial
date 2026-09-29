# ハマりポイント集

踏んだ落とし穴を**原因と対処のセット**で記録する。
他人の環境でも同じ問題が起きるため、**これ自体が資産**になる。
Phase A 完了条件のひとつであり、Phase B での納品物・提案材料にもなる。

## 書き方

1. [docs/templates/pitfall.md](../templates/pitfall.md) をコピー
2. ファイル名：`<ブロック>-<内容のスラッグ>.md`（例：`a1-clasp-path.md`）
3. **詰まって解決した直後に書く。** 後から書くと「なぜ詰まったか」が消える
4. 下の索引に1行追加する

## 書くときの基準

- **再現手順を書く。** 「たまに動かない」は記録として使えない
- **効かなかった対処も書く。** 他人に説明するとき、そこが一番効く
- **一般化できるか一言添える。** その環境固有か、どこでも起きるか

## 索引

| ID | ブロック | 事象 | 一般性 |
|---|---|---|---|
| [a1-clasp-nodenv-rehash](a1-clasp-nodenv-rehash.md) | A-1 | nodenv で `npm install -g` 直後に command not found | shim を使う環境全般 |
| [a1-clasp-rootdir-duplication](a1-clasp-rootdir-duplication.md) | A-1 | `--rootDir` 二重適用で `src/src/` に生成される | clasp 3.4.0 |
| [a1-clasp-push-silent-skip](a1-clasp-push-silent-skip.md) | A-1 | 非対話シェルで `clasp push` が黙ってスキップされる | どの環境でも |
| [a1-gas-default-timezone](a1-gas-default-timezone.md) | A-1 | 生成される `timeZone` が America/New_York | どの環境でも |
| [a1-clasp-logs-need-gcp-project](a1-clasp-logs-need-gcp-project.md) | A-1 | `clasp tail-logs` が GCP プロジェクト未設定で使えない | どの環境でも |
| [a1-gas-approved-but-nothing-happens](a1-gas-approved-but-nothing-happens.md) | A-1 | OAuth 承認は通るのに何も起きない（関数の既定選択 × 設定不足） | どの環境でも |
| [a1-gemini-free-tier-data-use](a1-gemini-free-tier-data-use.md) | A-1 | Gemini 無料枠は送信内容が学習・人間レビューの対象 | どの環境でも |
| [a1-gas-mailapp-vs-gmailapp-scope](a1-gas-mailapp-vs-gmailapp-scope.md) | A-1 | MailApp と GmailApp はスコープが別。診断の1行で権限が増える | どの環境でも |
| [a1-gemini-model-name-rot](a1-gemini-model-name-rot.md) | A-1 | ハードコードしたモデル名が提供終了で 404 になる | どの環境でも |
| [a1-gas-trigger-concurrency](a1-gas-trigger-concurrency.md) | A-1 | トリガー多重起動で二重処理（フラグ列だけでは防げない） | どの環境でも |
| [a1-gas-6min-execution-limit](a1-gas-6min-execution-limit.md) | A-1 | 実行時間6分制限（実測 約87件で打ち切り）と分割実行 | どの環境でも |
| [a1-external-api-retry-design](a1-external-api-retry-design.md) | A-1 | リトライ設計。本体は「再試行しない条件」の方 | どの環境でも |
| [a1-gas-consent-screen-is-not-read](a1-gas-consent-screen-is-not-read.md) | A-1 | 承認画面は読まれない。権限説明を画面に依存できない | どの環境でも |
| [a1-gas-granular-consent](a1-gas-granular-consent.md) | A-1 | 権限は個別に拒否できる。部分承認で「承認したのに動かない」 | どの環境でも |
| [a1-gas-trigger-cannot-be-transferred](a1-gas-trigger-cannot-be-transferred.md) | A-1 | トリガーは移管不可。所有権を移しても作成者で動く（未検証） | どの環境でも |
| [a2-evaluator-was-wrong](a2-evaluator-was-wrong.md) | A-2 | 評価する側の正解が誤っていた／意図しない汚れの混入 | どの環境でも |
| [a2-apple-silicon-x86-python](a2-apple-silicon-x86-python.md) | A-2 | Apple Silicon で x86_64 Python が選ばれ arm64 wheel が入らない | Intel 版 Homebrew が残る macOS |
| [a2-auto-scoring-cannot-be-trusted](a2-auto-scoring-cannot-be-trusted.md) | A-2 | 自動採点が誤答を正解と判定（期待値に誤答例を書いていた） | どの環境でも |
| [a2-privileged-port-check](a2-privileged-port-check.md) | A-2 | lsof でのポート確認は特権ポートを見落とす | どの環境でも |
| [a2-dify-default-chunking](a2-dify-default-chunking.md) | A-2 | Dify 既定チャンクは改行ごと。見出し・日付・表構造が本文から分離 | Dify 既定設定 |
| [a2-dify-chatflow-context-not-injected](a2-dify-chatflow-context-not-injected.md) | A-2 | チャットフローで引用は出るが回答に反映されない（{{#context#}} 手動挿入） | Dify チャットフロー |
| [a2-dify-selfhost-setup](a2-dify-selfhost-setup.md) | A-2 | Dify セルフホスト構築の落とし穴8件（Cloud混同・更新失敗・非推奨既定 等） | Dify セルフホスト |
| [a3-n8n-google-oauth-setup](a3-n8n-google-oauth-setup.md) | A-3 | n8n から Google を使う OAuth 設定。GAS で不要だった6手順と詰まり4箇所 | 外部ツール全般 |
| [a3-n8n-workflow-model](a3-n8n-workflow-model.md) | A-3 | n8n の処理モデルで踏んだ8件（アイテム展開・.first()・row_number 非対称 等） | ノードベースツール全般 |
| [a3-knowledge-curation-beats-instructions](a3-knowledge-curation-beats-instructions.md) | A-3 | 「外す」と決めた文書が投入されていた。ナレッジ管理は指示書に優先する | RAG・Project 全般 |
| [a3-error-detection-gas-vs-n8n](a3-error-detection-gas-vs-n8n.md) | A-3 | エラー検知の比較。Error Workflow はテストで動かない。setup 非冪等でフォーム増殖 | どの環境でも |
| [a3-n8n-item-multiplication](a3-n8n-item-multiplication.md) | A-3 | 参照データを読むと以降が行数倍で実行される。業務ルールをシートに置けない | ノードベースツール全般 |
| [a4-endpoint-protection-blocks-import](a4-endpoint-protection-blocks-import.md) | A-4 | エンドポイント保護のスキャンで新規パッケージの import が数十秒ブロックされる | EDR 導入端末すべて |
| [a4-windows-stdout-encoding](a4-windows-stdout-encoding.md) | A-4 | 日本語の print が Windows で落ちる。日本語 Windows では再現せず、自動実行だけが壊れる | 日本語を印字する Python 全般 |
| [a5a-js-rendered-silent-zero](a5a-js-rendered-silent-zero.md) | A-5a | JS 描画ページを静的取得すると10ページ巡回して0件・終了コード0。ページ送りだけが静的に存在する | ブラウザを使わない取得手段 |
| [a5a-robots-404-means-allow](a5a-robots-404-means-allow.md) | A-5a | robots.txt が404だと「許可」と表示される。確認したことにならない | urllib.robotparser 利用時 |
| [a5a-selector-break-is-silent](a5a-selector-break-is-silent.md) | A-5a | セレクタ破壊は例外を出さない。件数が正常なまま中身だけ空になり、差分検出も沈黙する | セレクタで抽出する実装すべて |

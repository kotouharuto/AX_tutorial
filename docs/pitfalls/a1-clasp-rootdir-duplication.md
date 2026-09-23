# clasp create-script --rootDir が二重適用され src/src/ にファイルが生成される

- **ブロック：** A-1
- **日付：** 2026-08-25
- **一般性：** clasp 3.4.0 で同じオプションを使えば誰でも
- **溶かした時間：** 約 0.1 時間

## 現象

```bash
clasp create-script --type sheets --title "A1-minimal" --rootDir src
```

出力は `└─ src/appsscript.json` と表示され成功に見えるが、実際の生成先は
`src/src/appsscript.json`。**表示されるパスと実際のパスが食い違う。**

## 原因

`.clasp.json` の `rootDir` に `"src"` が記録され、
clone 時のファイル書き出しでも `rootDir` が前置される。**rootDir が2回適用されている。**
表示は rootDir 相対（正しい）、書き出しは絶対（rootDir 重複）というずれ。

## 再現手順

1. 空ディレクトリで `clasp create-script --type sheets --rootDir src`
2. `find . -type f` で確認 → `./src/src/appsscript.json`

## 対処

生成後にファイルを1階層上げるだけでよい。`.clasp.json` の `rootDir` 設定自体は正しい。

```bash
mv src/src/appsscript.json src/appsscript.json && rmdir src/src
clasp status   # → Tracked files: src/appsscript.json （正しく認識される）
```

**`clasp status` が事実確認の手段になる。** push 前に必ず通す。

## 効かなかった対処

`.clasp.json` の `rootDir` を書き換えようとしたが不要だった。設定は最初から正しい。

## 他人の環境に納品するときの含意

**clasp の出力メッセージを信用せず、`clasp status` で追跡対象を確認してから push する。**
成功メッセージが出ても意図した構成になっていないことがある。
セットアップ手順書には「`clasp status` の期待出力」を明記しておく。

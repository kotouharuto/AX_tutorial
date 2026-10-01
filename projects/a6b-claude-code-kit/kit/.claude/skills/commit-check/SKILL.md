---
description: コミット前に差分を確認し、秘密情報の混入と不要なファイルを検出する
when_to_use: コミットする直前。ユーザーが「コミットする」と言ったときにも使う
argument-hint: "[なし]"
allowed-tools: Bash(git status) Bash(git diff:*) Bash(git ls-files:*) Read
disable-model-invocation: false
---

ステージされた差分を確認し、**コミットしてよいかを判断する材料**を出す。

## 手順

1. ステージされた内容を確認する

```
!`git diff --cached --stat`
```

2. 秘密情報が混ざっていないかを調べる

```
!`git diff --cached --name-only`
```

次のいずれかに当てはまるファイルがあれば**必ず指摘する**。

- `.env`、`.env.*`（`.env.example` は除く）
- `*.pem`、`*.key`、`id_rsa`、`.ssh/` 配下
- `credentials`、`secret`、`token` を名前に含むもの
- サービスアカウントの JSON 鍵

3. 差分の中身に値が直書きされていないかを調べる

ファイル名が安全でも、**中身に API キーが書かれている**ことがある。
`git diff --cached` の追加行から、次のような形を探す。

- 20文字以上の英数字が代入されている行
- `Bearer `、`sk-`、`ghp_`、`AKIA` などで始まる文字列
- 接続文字列（`://user:password@`）

4. 生成物・一時ファイルが混ざっていないかを調べる

`__pycache__`、`.venv`、`node_modules`、`dist`、`build`、
`.DS_Store`、`*.log`、テストの出力など。

## 出力

**見つかった問題を列挙し、問題がなければ「なし」と明示する。**
「問題ありません」だけで終わらせず、**何を確認したか**を併記する。

```
確認した項目：ファイル名（秘密情報）/ 差分の中身（直書き）/ 生成物
検出した問題：なし
```

問題があった場合、**こちらでコミットを実行しない。**
除外の方法（`git restore --staged <path>`、`.gitignore` への追記）を示し、
ユーザーの判断を待つ。

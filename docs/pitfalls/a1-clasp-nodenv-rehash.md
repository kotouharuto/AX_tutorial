# nodenv 環境で npm install -g した直後、コマンドが command not found になる

- **ブロック：** A-1
- **日付：** 2026-08-25（事象の発生は 2026-08-23）
- **一般性：** nodenv / rbenv / pyenv 系の shim を使う環境なら誰でも
- **溶かした時間：** 不明（記録開始前に自然解消していた）

## 現象

```
npm install -g @google/clasp   # 成功
clasp login                    # command not found
```

## 原因（推定）

nodenv は `~/.nodenv/shims/` に置いた **shim** 経由でコマンドを解決する。
`npm install -g` で入るのは `~/.nodenv/versions/<ver>/bin/` の実体であり、
**shim は自動生成されない。** shim が無い間、PATH が正しくてもコマンドは見えない。

`nodenv rehash`（または新しいシェルの起動）で shim が生成されて解決する。

**当初 PATH 未設定を疑ったが誤り。** 検証時点で PATH には
`~/.nodenv/shims` が最初から含まれていた。切り分けの順序を間違えていた。

## 再現手順

1. nodenv で Node を管理している状態にする
2. `npm install -g <パッケージ>`
3. 同じシェルで即座にコマンドを叩く → `command not found`

## 対処

```bash
nodenv rehash
```

**切り分けの正しい順序（次から使う）:**

1. `npm prefix -g` でグローバル prefix を出す
2. `ls $(npm prefix -g)/bin/ | grep <コマンド>` で**実体があるか**を先に見る
3. 実体がある → shim / PATH の問題（rehash を試す）
4. 実体が無い → インストールが失敗している（権限エラーを疑う）

## 効かなかった対処

`~/.bash_profile` への PATH 追記を疑ったが、そもそも PATH は通っていたので無意味だった。
**「command not found = PATH の問題」と短絡すると、shim 系の環境で必ず遠回りする。**

## 他人の環境に納品するときの含意

相手の環境が nodenv / nvm / asdf / Homebrew Node のどれかで、グローバルコマンドの
挙動が変わる。**セットアップ手順書に「実体があるか確認する」ステップを入れる。**
可能なら `npx` 経由に寄せ、グローバルインストールを前提にしない手順にする。

# 導入手順書

新規リポジトリに Claude Code の共通設定を入れる手順。**所要時間の目安は30分。**

照合日 2026-10-02 時点の仕様に基づく（→ `docs-verification.md`）。
**手順どおりで動かない場合は仕様が変わった可能性がある。** 照合記録を先に確認する。

---

## 前提

- Claude Code がインストール済みで、`claude` コマンドが動く
- 対象のリポジトリが git リポジトリである（`git init` 済み）
- このキットの `kit/` ディレクトリが手元にある

確認：

```bash
claude --version
git rev-parse --is-inside-work-tree
```

2つ目が `true` を返さない場合、リポジトリの中にいない。移動してから進む。

---

## 1. ファイルを配置する（5分）

対象リポジトリの直下で実行する。`<KIT>` はこのキットの `kit/` の絶対パス。

```bash
mkdir -p .claude/skills
cp -R <KIT>/.claude/settings.json .claude/settings.json
cp -R <KIT>/.claude/skills/. .claude/skills/
cp <KIT>/CLAUDE.md CLAUDE.md
cp <KIT>/.mcp.json .mcp.json
```

配置後の確認：

```bash
ls -1 .claude/settings.json CLAUDE.md .mcp.json
ls -1 .claude/skills/
```

**`.claude/skills/` に `commit-check` と `explain-change` の2つのディレクトリがあること。**
`SKILL.md` が直接 `.claude/skills/` に置かれている状態は誤り
（`.claude/skills/<名前>/SKILL.md` の形が必要）。

```bash
ls -1 .claude/skills/*/SKILL.md
```

---

## 2. `.gitignore` を確認する（3分）

**コミットするもの**と**しないもの**を分ける。

```bash
cat >> .gitignore <<'EOF'

# Claude Code
.claude/settings.local.json
EOF
```

| ファイル | コミットするか | 理由 |
|---|---|---|
| `CLAUDE.md` | **する** | チームで共有する前提 |
| `.claude/settings.json` | **する** | チーム共有の権限設定 |
| `.claude/skills/` | **する** | チームで使うスキル |
| `.mcp.json` | **する** | チーム共通の MCP 設定 |
| `.claude/settings.local.json` | **しない** | 各自の上書き用 |

**`.claude/` 全体を `.gitignore` に入れないこと。** 入れると共有設定が配られない。

---

## 3. `CLAUDE.md` を埋める（10分）

`<>` の箇所を埋める。**埋めずに配らない。**
埋まっていない雛形は、読む側に「読まなくてよい文書」だと判断される。

最低限、次の3つは必ず埋める。

1. **「このリポジトリは何か」** — これが無いと、毎回説明することになる
2. **「セキュリティ」** — 何をコミットしてはいけないか
3. **「やってはいけないこと」** — 暗黙の了解は新しく入った人に伝わらない

「説明の粒度」は後回しでもよいが、**空欄のまま残さず節ごと削る。**

---

## 4. MCP サーバを設定する（5分）

`.mcp.json` はプロジェクト共有の MCP 設定。**リポジトリ直下に置く**
（`.claude/mcp.json` ではない）。

キットには例として context7（ライブラリのドキュメント参照）が入っている。
**不要なら削る。** 使う場合は各自が環境変数を設定する。

```bash
export CONTEXT7_API_KEY=<各自のキー>
```

> **キーを `.mcp.json` に直書きしない。** このファイルはコミットする。
> `${VAR}` と `${VAR:-既定値}` で環境変数を参照できる。
>
> ただし `ANTHROPIC_API_KEY` など一部の資格情報系の変数名は、
> **リモートサーバの URL・ヘッダでは展開されない**（公式仕様）。
> 展開されているか不明な場合は、サーバが接続できるかで確認する。

### 自作の MCP サーバを追加する場合

```bash
claude mcp add --transport stdio <サーバ名> --scope project -- <起動コマンド>
```

`--scope project` を付けると `.mcp.json` に書かれ、チームに共有される。
付けないと `~/.claude.json` に書かれ、**自分だけに効く**。

---

## 5. 動作を確認する（5分）

```bash
claude
```

初回は**ワークスペースの信頼ダイアログ**が出る。承認すると `.mcp.json` のサーバが読み込まれる。

確認する項目：

```
□ /commit-check と入力して、スキルが候補に出る
□ /explain-change と入力して、スキルが候補に出る
□ /mcp と入力して、context7 が接続済みになっている（使う場合）
□ `cat .env` のような操作を依頼して、拒否される
□ `git push` を依頼して、確認を求められる
```

4つ目と5つ目が**権限設定が効いているかの確認**になる。
拒否も確認もされずに実行された場合、`.claude/settings.json` が読まれていない。

### スキルが候補に出ない場合

- `.claude/skills/<名前>/SKILL.md` の形になっているか確認する
- `SKILL.md` の先頭が `---` で始まり、`description` があるか確認する
- セッションを開始した後に `~/.claude/skills/` を新規作成した場合は `/reload-skills`

---

## 6. 各自の上書き（任意・2分）

チーム共有の設定を変えずに自分だけ変えたい場合は `.claude/settings.local.json` に書く。
このファイルはコミットしない。

```json
{
  "permissions": {
    "allow": ["Bash(npm run test:*)"]
  }
}
```

### 権限モードについての注意

**`permissions.defaultMode` の `auto` と `bypassPermissions` は、
プロジェクト設定・ローカル設定からは反映されない**（公式仕様）。

| 設定したい場所 | 効くか |
|---|---|
| `.claude/settings.json`（共有） | **効かない** |
| `.claude/settings.local.json`（ローカル） | **効かない** |
| `~/.claude/settings.json`（ユーザー） | 効く |
| 管理者設定 | 効く |
| `claude --permission-mode <mode>` | 効く（そのセッションのみ） |

**このキットの `.claude/settings.json` に `defaultMode` を入れていないのは、
入れても効かず「設定したのに反映されない」と時間を溶かすため。**
チーム全体に適用したい場合は、各自のユーザー設定か管理者設定で行う。

---

## 完了の判定

次がすべて満たせていれば完了。

```
□ .claude/settings.json / CLAUDE.md / .mcp.json が配置されている
□ .claude/skills/<名前>/SKILL.md の形で2つ以上ある
□ CLAUDE.md の <> が残っていない（必須3項目）
□ .gitignore に .claude/settings.local.json が入っている
□ /commit-check と /explain-change が候補に出る
□ .env の読み取りが拒否される
□ git push が確認を求められる
```

---

## フックを追加する場合（任意）

キットにフックは入れていない。**他人の環境で壊れやすい**ため。
追加するなら、次の3点を必ず守る。

### 1. 絶対パスを直書きしない

```json
{ "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/check.sh", "args": [] }
```

`/path/to/check.sh` のような**雛形のままのパスを残さない。**
スクリプトが存在しない場合、**フックは失敗するがツールの実行は止まらない**（公式仕様）。
つまり「設定したのに何も起きていない」状態になり、気づけない。

### 2. 依存するコマンドが入っているか確認する

`prettier`、`jq`、`ruff` などを呼ぶフックは、**入っていない環境で失敗する。**
しかも対象の拡張子を触らない限り発火しないため、
**入れた直後は正常に見えて、後から壊れる。**

```bash
which jq prettier ruff
```

### 3. OS 依存のコマンドを使わない

`osascript`（macOS）、`notify-send`（Linux）などは他の OS で動かない。
チームの OS が揃っていない場合は使わない。

### 動いているかの確認方法

**設定しただけで動いていると判断しない。** 実際に発火させて出力を見る。

```bash
# 例：PostToolUse のログを仕込んでおき、ファイルを編集してから確認する
tail -5 /tmp/claude-hook.log
```

# 公式ドキュメントとの照合記録

到達条件「機能に関する記述が公式ドキュメントと照合済み」の根拠。

**照合日：2026-10-02**

Claude Code の設定・機能は変更が速い。**この記録の日付から離れたら再照合する。**
特に下の「私の認識と違った点」は、過去の書き方がそのまま動くために
古い記述だと気づきにくい。

## 参照した URL

| ページ | URL |
|---|---|
| 設定ファイルと優先順位 | https://code.claude.com/docs/en/settings |
| スラッシュコマンド | https://code.claude.com/docs/en/slash-commands |
| スキル | https://code.claude.com/docs/en/skills |
| フック | https://code.claude.com/docs/en/hooks |
| MCP | https://code.claude.com/docs/en/mcp |

### ドメインが移動している

**`docs.claude.com/en/docs/claude-code/...` は `code.claude.com/docs/en/...` へ 301 リダイレクトする。**

手順書や社内 Wiki に旧 URL を貼っていると、リダイレクトが切れた時点で参照不能になる。
**この キットのリンクは新ドメインに統一した。**

---

## 私の認識と違った点（4件）

キットの設計に直接影響したもの。照合しなければ古い形で書いていた。

### 1. カスタムコマンドはスキルに統合された

公式の記述：「Custom commands have been merged into skills.」

| | コマンド（旧） | スキル（現行） |
|---|---|---|
| 置き場所 | `.claude/commands/deploy.md` | `.claude/skills/deploy/SKILL.md` |
| 呼び出し | `/deploy` | `/deploy`（同じ） |
| 補助ファイル | **不可** | 可（`reference.md`、`scripts/` など） |
| 変更の反映 | **再起動が必要** | **セッション中に自動反映** |
| `name` / `paths` | 非対応 | 対応 |

既存の `.claude/commands/` は動き続けるが、**新規はスキルで作る。**

→ **このキットはスキル形式で雛形を用意した。**
同名のスキルとコマンドが両方ある場合、スキルが優先されコマンドは置き換わる。

### 2. `permissions.defaultMode` の一部はプロジェクト設定では効かない

公式の記述：`auto` と `bypassPermissions` は
**プロジェクト設定・ローカル設定からは反映されない。**
ユーザー設定か管理者設定に書くか、`--permission-mode` で都度渡す。

（v2.1.257 より前は `bypassPermissions` がどのファイルからでも効いた。）

→ **キットの `.claude/settings.json` に `defaultMode` を入れていない。**
入れても効かず、「設定したのに反映されない」という形で時間を溶かす。
チーム全体に適用したい場合は各自のユーザー設定か管理者設定で行う。

### 3. プロジェクト共有の MCP 設定は `.mcp.json`（リポジトリ直下）

`.claude/mcp.json` ではない。スコープは3種類。

| スコープ | 置き場所 | 共有されるか |
|---|---|---|
| local（既定） | `~/.claude.json` | されない |
| **project** | **`.mcp.json`（リポジトリ直下）** | **される（コミットする）** |
| user | `~/.claude.json` | されない |

環境変数は `${VAR}` と `${VAR:-default}` で展開できる（`command`・`args`・`env`・`url`・`headers`）。

**ただし `ANTHROPIC_API_KEY` などの資格情報系の変数名は、
リモートサーバの URL・ヘッダでは展開されない**（安全のため）。
資格情報を渡すときは別の変数名を使う。

初回は**ワークスペースの信頼ダイアログ**の承認が必要。
非対話実行（`claude -p`、SDK）では確認なしで読み込まれるため、
止めたい場合は `disabledMcpjsonServers` か `--strict-mcp-config` を使う。

### 4. フックの `type` は command 以外に4種類ある

`command` / `http` / `mcp_tool` / `prompt` / `agent`。

制御の方法も複数ある。

| 方法 | 挙動 |
|---|---|
| 終了コード 0 | 標準出力の JSON を読む |
| **終了コード 2** | **動作をブロックする** |
| それ以外の終了コード | **ブロックしないエラー。動作は続行する** |

**3行目が重要。** スクリプトが存在しない・実行できない場合、
フックは失敗するが**ツールの実行は止まらない**。
つまり「フックを設定したのに何も起きていない」状態になり、気づけない。

PreToolUse で明示的に許可・拒否するには JSON を返す。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "理由"
  }
}
```

---

## 照合して確認した仕様（キットが依存している部分）

### 設定ファイルの優先順位（高い順）

1. 管理者設定（`managed-settings.json`、MDM、コンソール）
2. コマンドライン（`claude --settings`）
3. **プロジェクトのローカル設定（`.claude/settings.local.json`）** — 個人用・コミットしない
4. **プロジェクトの共有設定（`.claude/settings.json`）** — チーム共有・コミットする
5. ユーザー設定（`~/.claude/settings.json`）

→ キットが配るのは **4番の `.claude/settings.json`**。
個人の上書きは3番で各自が行う。

### スキルの置き場所と読み込み

| スコープ | 置き場所 |
|---|---|
| 個人 | `~/.claude/skills/<name>/SKILL.md` |
| **プロジェクト** | **`.claude/skills/<name>/SKILL.md`** |
| ネスト | `<subdir>/.claude/skills/<name>/SKILL.md` |

- セッション開始時にディレクトリを走査する
- **説明文だけを先に読み、本文は呼び出し時に読む**
- `SKILL.md` の変更はセッション中に反映される（再起動不要）
- `~/.claude/skills/` を起動後に新規作成した場合は `/reload-skills` が必要
- プラグインの `hooks/`・`.mcp.json`・`agents/` の変更は `/reload-plugins` が必要

### フックの置き場所

| 置き場所 | 共有されるか |
|---|---|
| `~/.claude/settings.json` | されない |
| **`.claude/settings.json`** | **される** |
| `.claude/settings.local.json` | されない |
| プラグインの `hooks/hooks.json` | される |
| スキル・サブエージェントの frontmatter | される |

プロジェクトのスキル・サブエージェントの frontmatter に書いたフックは、
**ワークスペースの信頼を承認した後に動く。**

### パスの参照

`${CLAUDE_PROJECT_DIR}` でリポジトリ直下を参照できる。
**フックのコマンドに絶対パスを直書きしない**（他人の環境で壊れる）。

```json
{ "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/check.sh", "args": [] }
```

---

## 再照合のタイミング

次のいずれかに当てはまったら、このファイルを更新してから手順書を配る。

- 照合日から3か月以上経った
- 手順どおりにやって動かない報告が来た
- Claude Code のメジャーバージョンが上がった

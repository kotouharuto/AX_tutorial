# 定期実行は対話シェルと別世界。PATH・TCC・iCloud で3連続で止まった

- **ブロック：** A-5a
- **日付：** 2026-09-30
- **一般性：** macOS の launchd。**PATH と保護フォルダの話は Windows タスクスケジューラも同型**
- **溶かした時間：** 約 1.5 h（うち約 40 分はディレクトリ移動の待ち時間）

## 事象

手元のターミナルで問題なく動くバッチを launchd に載せたら、**3回連続で失敗した。**
いずれも「対話シェルでは動くのに定期実行だけ壊れる」型。

| # | 症状 | 終了コード |
|---|---|---|
| 1 | `uv: command not found` | 127 |
| 2 | `OSError: [Errno 11] Resource deadlock avoided` | 1 |
| 3 | （移動後）`bad interpreter: No such file or directory` | 126 相当 |

## 1つ目：PATH に ~/.local/bin が無い

launchd は `~/.zshrc` や `~/.zprofile` を読まない。
`uv` は `~/.local/bin` にあるため見つからない。

事前に確認できる。

```bash
launchctl getenv PATH
# → 空。launchd は最小限の PATH を使う
```

### 対処

uv を経由せず、**仮想環境の python を絶対パスで直接呼ぶ。**

```xml
<key>ProgramArguments</key>
<array>
    <string>/Users/haruto/dev/ax_tutorial/projects/a5a-scraping/.venv/bin/python</string>
    <string>/Users/haruto/dev/ax_tutorial/projects/a5a-scraping/src/run.py</string>
</array>
```

`uv run` を使わない理由はもう1つある。**定期実行のたびに依存を解決させない。**
ネットワークが切れていると `uv run` はそこで止まる。
依存の同期は配備時に済ませる。

## 2つ目：TCC が ~/Desktop を拒否する（エラー文から原因が読めない）

絶対パス指定にしても落ちた。しかもメッセージが原因を示さない。

```
Fatal Python error: init_import_site: Failed to import the site module
  File "<frozen site>", line 618, in venv
OSError: [Errno 11] Resource deadlock avoided
```

`Resource deadlock avoided` からファイルアクセス権を疑うのは難しい。

### 切り分け：最小の plist を別に作る

**エラー文が原因を示さないときは、疑う対象だけを実行する plist を作る。**

```xml
<string>cat /Users/haruto/Desktop/.../.venv/pyvenv.cfg; echo "exit=$?";
        ls /Users/haruto/Desktop >/dev/null; echo "ls exit=$?";
        /Users/haruto/.local/share/uv/python/.../python3.13 -c "print('base ok')"</string>
```

結果で原因が確定した。

```
cat: .../.venv/pyvenv.cfg: Operation not permitted
ls:  /Users/haruto/Desktop: Operation not permitted
base ok                                        ← Desktop の外は動く
```

**launchd から起動したプロセスは ~/Desktop を読めない**（macOS の TCC）。
Desktop の外にあるベース Python は同じ launchd から正常に動いた。
つまり plist の設計は正しく、**置き場所だけが問題**だった。

`Resource deadlock avoided` は、Python の `site` モジュールが
TCC 拒否を受けた結果の二次症状にすぎない。

### さらに悪い条件：iCloud Drive の同期対象だった

移動しようとした `mv` が CPU 0% のまま9分以上返らなかった。
同一ボリューム内のリネームなら一瞬で終わるはずのものが終わらない。

```bash
ps aux | sort -rn -k3 | head
# 114%  fileproviderd
#  48%  bird（iCloudDriveCore）
#  88%  com.broadcom.mes（エンドポイント保護）
```

**~/Desktop は iCloud Drive の同期対象**だった。
リネームではなく、実体化（ダウンロード）＋同期解除＋スキャンが走っていた。
`mv` の所要時間は**約40分**。

同期下は TCC 以前に定期実行の置き場所として不適切。

- ファイルが「クラウドのみ」状態だと読み込みでダウンロードが走り、オフラインで失敗する
- バッチが書いた出力が同期の競合を起こす
- 競合すると**エラーを出さずに古いデータを読む**ことがある
  （A-3 の SQLite WAL で踏んだ「古いスナップショットを見る」と同型）

### 対処

**保護対象フォルダ（Desktop / Documents / Downloads）に定期実行の対象を置かない。**
`~/dev` へ移した。

フルディスクアクセスを付与する手もあるが採らなかった。
顧客に「バッチのために全ディスクアクセスを許可してください」と言う提案は通らない。
**置き場所で解決できるものを権限で解決しない。**

## 3つ目：移動で venv のラッパーだけが壊れる

移動後、`.venv` について自分の予想が外れた。

| 対象 | 実際 |
|---|---|
| `.venv/bin/python` | **壊れない**。ツリー外のベース Python へのシンボリックリンク |
| パッケージの読み込み | **壊れない**。実行ファイル位置からの相対解決（`sys.prefix` も新パスを指す） |
| `.venv/bin/pytest` などのラッパー | **壊れる**。shebang に旧絶対パスが埋まっている |
| `activate` スクリプト | 壊れる（同じ理由） |

```bash
head -1 .venv/bin/pytest
# #!/Users/haruto/Desktop/ax_tutorial/projects/a5a-scraping/.venv/bin/python
```

**`uv sync` では直らない。** uv は既存の venv を「監査済み」と判断し、
ラッパーを再生成しない。

### 対処

`bin/` 配下のテキストファイルの旧パスを書き換える（3プロジェクト計44件）。
再ダウンロードが不要なので、スキャン待ちも避けられる。

```python
for path in bin_dir.iterdir():
    if not path.is_file() or path.is_symlink():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue  # バイナリは触らない
    if OLD in text:
        path.write_text(text.replace(OLD, NEW), encoding="utf-8")
```

なお `python -m pytest` ならラッパーを経由しないので、壊れていても動く。

### 副作用で踏んだミス

修復のつもりで `uv sync --extra dev` を実行したら、**playwright が削除された。**

```
- playwright==1.63.0
```

`uv sync` は**指定しなかった任意依存を消す**。
任意依存を複数持つプロジェクトでは、毎回すべての extra を指定する必要がある。

## plist 側で決めたこと

### RunAtLoad を入れない

検証中は結果をすぐ見たいので `RunAtLoad` を使ったが、実運用では外した。
**ログイン時や再登録の直後に走り、意図しないタイミングで取得先へアクセスする。**
手動で試すときは `launchctl kickstart -k gui/$(id -u)/<Label>` を使う。

### 標準出力の行き先を必ず指定する

**画面が無いので、指定しないと何も分からない。**
1つ目の失敗（`uv: command not found`）が分かったのは、
`StandardErrorPath` を設定していたからだった。

```xml
<key>StandardOutPath</key>
<string>.../output/launchd.out.log</string>
<key>StandardErrorPath</key>
<string>.../output/launchd.err.log</string>
```

アプリ側でもログをファイルに残している（`run.py` の `log()`）。
**plist のリダイレクトとアプリのログは別物**で、前者は起動失敗を、
後者は処理内容を拾う。1つ目の失敗では後者に何も出なかった。

### スリープ中の予定時刻

`StartCalendarInterval` は、スリープ中に予定時刻を過ぎた場合、
復帰後にまとめて1回実行する。**実行されない日がある**のではなく
**遅れて実行される**。時刻の厳密さが要る用途には向かない。

## 検証した内容

```
1回目（手動 kickstart） exit 0  取得100件・異常なし・差分なし
2回目（5分後・自動）     exit 0  StartInterval による自動実行を確認
→ 実運用設定（1日1回 07:00）に切り替え、kickstart で再確認  exit 0
```

## 一般化

- **定期実行は別の環境で動く別のプログラムだと考える。** PATH、cwd、権限、
  標準出力の行き先が対話シェルと違う。「手元で動いた」は根拠にならない
- **エラー文が原因を示さないときは、疑う対象だけを実行する最小の再現を作る。**
  `Resource deadlock avoided` を読み続けても TCC には到達しない
- **置き場所で解決できるものを権限で解決しない。** フルディスクアクセスは
  動くが、顧客に要求できない
- Windows タスクスケジューラでも同じ3点を確認する必要がある。
  PATH（環境変数がユーザーセッションと異なる）、cwd（`system32` になる）、
  **コンソールがない**（→ `a4-windows-stdout-encoding.md`）

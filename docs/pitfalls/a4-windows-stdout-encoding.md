# 日本語の print が Windows で落ちる。しかも日本語 Windows では再現しない

- **ブロック：** A-4
- **日付：** 2026-09-27
- **一般性：** 日本語を画面出力する Python スクリプトを Windows で動かす場合すべて
- **溶かした時間：** 約 0.3 時間（CI のログに原因がそのまま出ていたため）

## 事象

macOS で完成させたバッチを GitHub Actions に載せたところ、
**ubuntu-latest と macos-latest は success、windows-latest だけ failure。**

落ちたのはテストですらなく、その前のテストデータ生成だった。

```
print(f"生成完了: {len(created)} ファイル → {OUT_DIR}")
  File "...\encodings\cp1252.py", line 19, in encode
UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-3:
character maps to <undefined>
```

`position 0-3` は「生成完了」の4文字。**1文字目から出せていない。**

## 原因

Windows の Python は **stdout のエンコーディングを OS のロケールから決める**。
ファイル書き込みと違い、`print` には `encoding=` を書く場所がないので見落とす。

印字している非ASCII文字（51種）を文字コード別に判定した結果：

| 環境 | stdout の既定 | 51種のうち出せない文字 |
|---|---|---|
| macOS / Linux | UTF-8 | 0 |
| **日本語 Windows のコンソール** | cp932 | **0（動いてしまう）** |
| **英語ロケールの Windows / CI** | cp1252 | **51（全滅）** |

```bash
# 判定に使ったコード
python3 -c "
chars = {c for c in open('prints.txt', encoding='utf-8').read() if not c.isascii()}
for enc in ('cp932', 'cp1252'):
    ng = [c for c in sorted(chars) if not _ok(c, enc)]
    print(enc, len(ng))
"
```

## ここが厄介な点

**実機があっても手動実行では気づけない。**

顧客が日本語 Windows でダブルクリック実行すれば、コンソールは cp932 なので通る。
壊れるのは次のときだけ：

- 英語ロケール／他言語ロケールの端末
- **タスクスケジューラ経由の自動実行**（コンソールを持たない）
- `python main.py > log.txt` のようなリダイレクト
- CI、コンテナ、SSH 越しの実行

つまり「**手で動かすと動くのに、自動化した途端に落ちる**」という形で出る。
A-4 は「自動で回すバッチ」を作っているので、実運用そのものが壊れる条件に当たる。

Phase A で繰り返し出た「エラーにならず成功したように見える」型の**裏返し**で、
こちらは「**手元では成功するので、壊れていることに気づけない**」型。

## 対処

### 採った方法：コード側で stdout を UTF-8 に固定する

```python
# src/console.py
def force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        # capsys 等で TextIOWrapper でない場合は reconfigure を持たないので飛ばす
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
```

これを各エントリポイント（`main.py` / `generate_testdata.py` / `naive_aggregate.py`）の
`main()` 冒頭で呼ぶ。

`errors="replace"` にしたのは、**印字は進捗表示にすぎない**から。
成果物はすべて `encoding=` を明示してファイルへ書いているので、
表示できない文字のためにバッチ全体を落とす方が損失が大きい。

### 採らなかった方法：環境変数（`PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`）

CI のワークフローに1行足せば緑にはなる。**が、これは直したことにならない。**

環境変数はワークフローや起動スクリプトの設定であって、**配布先には付いていかない**。
CI だけが通り、顧客環境の不具合は残る。
「CI を通すための細工」と「不具合の修正」を混同すると、
後者をやったつもりで前者だけが終わる。

### リグレッションを検知する仕掛け

修正すると CI が緑になるので、**将来この呼び出しが抜けても気づけなくなる。**
そこで、日本語を1文字も出せない文字コードを明示的に強制するステップを足した。

```yaml
      # console.force_utf8_stdio() の呼び出しが抜けると、このステップだけが落ちる。
      # 全 OS で走らせる理由：Windows ランナーのロケール設定に検知を依存させないため。
      - name: 日本語を出せない文字コードでも落ちないことを確認
        env:
          PYTHONIOENCODING: cp1252
        run: uv run python src/main.py
```

ubuntu / macos でも走るので、**Windows ランナーがなくても**検知できる。

### 配布先の環境を記録に残す

`output/load_report.txt` に実行環境を書き出すようにした。

```
実行環境: darwin / Python 3.13.11 / stdout=utf-8
```

顧客から「動かない」と言われたときに、
**このファイルを送ってもらえば環境差を切り分けられる**。

## 一般化

- **`print` にも文字コードがある。** ファイル I/O だけ `encoding=` を書いて安心しない
- **OS ではなくロケールで壊れる。** 「Windows で動くか」ではなく
  「どのロケールの Windows で動くか」を問う必要がある
- **実機の有無と検証の質は別。** 実機を手動で触るより、
  敵対的な環境変数を CI で強制する方が確実に見つかる。
  今回は実機なしで、実機の手動確認では見つからない不具合を捕まえた
- CI を OS マトリクスで回す価値は「**手元と違う条件を自動で踏んでくれること**」にある。
  条件が手元と同じなら、OS を増やしても意味は薄い

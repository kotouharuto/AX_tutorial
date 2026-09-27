# robots.txt が無いと「許可」と表示される。確認したことにならない

- **ブロック：** A-5a
- **日付：** 2026-09-27
- **一般性：** `urllib.robotparser` を使う実装すべて。受注判断そのものにも関わる
- **溶かした時間：** 0.2 h

## 事象

取得より先に robots.txt を確認するスクリプトを書き、練習用サイトに対して実行した。

```
=== https://books.toscrape.com/robots.txt ===
  robots.txt が存在しない（404）

=== 各 URL の可否 ===
  許可  https://books.toscrape.com/  (UA=*)
```

**robots.txt が無いのに「許可」と出る。**
自分で書いたスクリプトなのに、出力を見て一瞬「許可されている」と読んでしまった。

## 原因

`RobotFileParser.read()` は HTTP ステータスによって内部状態を変える。
404 を受けると `allow_all = True` になり、以降 `can_fetch()` は常に True を返す。

慣習としては正しい（規定が無いので制限されない）。
問題は**出力が2つの異なる意味を同じ言葉で表していた**こと。

| 表示 | 実際の意味 |
|---|---|
| 許可 | robots.txt に許可が書かれている |
| 許可 | **robots.txt が無く、規定が存在しない** |

後者は「確認した結果の許可」ではない。

## 挙動の確認

どの状況で何を返すかを実際に調べた。

```python
from urllib.robotparser import RobotFileParser

p = RobotFileParser(); p.set_url("https://example.invalid/robots.txt")
p.can_fetch("*", "https://example.invalid/any")   # → False（read() 未実行）

p2 = RobotFileParser(); p2.set_url("https://no-such-host.invalid/robots.txt")
p2.read()                                          # → URLError
p2.can_fetch("*", "https://no-such-host.invalid/any")  # → False

p3 = RobotFileParser(); p3.parse([])
p3.can_fetch("*", "https://x/any")                 # → True（空＝制限なし）

p4 = RobotFileParser(); p4.parse(["User-agent: *", "Disallow: /"])
p4.can_fetch("*", "https://x/any")                 # → False
```

| 状況 | `can_fetch` | 評価 |
|---|---|---|
| `read()` 未実行 | **False** | 安全側 |
| `read()` が失敗（到達不能） | **False** | 安全側（fail-closed） |
| robots.txt が 404 | **True** | 慣習上は正しいが誤読しやすい |
| `Disallow: /` | False | 正しい |

**取得に失敗したときは禁止扱いになる**ので、ライブラリの設計自体は安全側だった。
危ないのは 404 のケース。

## 対処

表示で2つを区別する。

```python
has_robots = fetch_robots_text(origin) is not None
...
if not allowed:
    mark = "**禁止**"
elif has_robots:
    mark = "許可（明示）"
else:
    mark = "許可（robots.txt なし・規定がないだけ）"
```

あわせて、判断を誤らせない注意書きを必ず出力する。

```
- Crawl-delay の指定が無くても間隔を空ける。指定なし＝無制限ではない
- robots.txt が無いことは許可の根拠にならない。利用規約の確認が別に必要
- robots.txt を読めなかったときは禁止として扱う（確認できない＝許可ではない）
```

## 受注判断への含意（重要）

robots.txt は**判断材料の1つでしかない。** 揃っていても足りない。

| 確認項目 | robots.txt で分かるか |
|---|---|
| クローラへの規定 | 分かる（あれば） |
| **利用規約での禁止** | **分からない。別途読む** |
| ログインの要否 | 分からない |
| 個人情報を含むか | 分からない |
| アクセス頻度の妥当性 | Crawl-delay があれば一部 |

**「robots.txt を確認しました」を根拠として提示しない。**
顧客に対して安全性を説明する材料としては不足しており、
後で問題になったときに「確認した」と言った側の責任になる。

## 一般化

- **確認できなかったことを、許可として扱わない。** これはスクレイピングに限らない
- **自分が書いた出力ほど誤読する。** 「許可」の一語に2つの意味を持たせたのは自分で、
  それを自分で読み間違えた。**表示は判断の単位で分ける**
- ライブラリの既定が安全側か危険側かは、**壊れた状況を作って確かめる**のが早い。
  今回は到達不能ホストと空 robots.txt の両方を試して確認した

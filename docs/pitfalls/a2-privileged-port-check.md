# ポートの空き確認に lsof を使うと、特権ポートの使用を見落とす

- **ブロック：** A-2
- **日付：** 2026-09-08
- **一般性：** どの環境でも（macOS / Linux 共通）
- **溶かした時間：** 約 0.1 時間

## 事象

Dify をセルフホストで起動する前に、ポートの空きを確認した。

```bash
$ lsof -nP -iTCP:80 -sTCP:LISTEN >/dev/null 2>&1 && echo "使用中" || echo "空き"
:80 空き        # ← 誤り
```

「空き」と判定して起動したところ、nginx だけが失敗した。

```
Error response from daemon: ports are not available:
exposing port TCP 0.0.0.0:80 -> 127.0.0.1:0:
listen tcp 0.0.0.0:80: bind: address already in use
```

## 原因

**`lsof` は、自分の権限で見えるプロセスしか表示しない。**

80番のような特権ポート（1024未満）を LISTEN できるのは root なので、
sudo なしの `lsof` では**そのプロセスが存在しないように見える。**

`netstat` なら権限に関係なく見える。

```bash
$ netstat -an | grep LISTEN | grep -E '\.80 '
tcp46      0      0  *.80                   *.*                    LISTEN     # ← 使用中だった
```

## なぜ危険か

**「空き」という誤った判定が、エラーではなく成功として返る。**

`lsof` の終了コードは「見つからなかった」を意味するだけで、
「存在しない」ことは保証しない。**見えないことを、無いことと解釈した。**

A-1 の `clasp push` が終了コード0で何もしなかった件と同じ構造
（→ [記録](a1-clasp-push-silent-skip.md)）。
**コマンドが成功した＝意図した状態である、とは限らない。**

## 対処

### ポート確認は netstat を使う

```bash
netstat -an | grep LISTEN | grep -E '\.80 '
```

`lsof` を使うなら sudo を付ける。ただし他人の環境で sudo を要求する手順は
セットアップの障害になるので、**権限不要な netstat を選ぶ方が実務的。**

### 今回の対処

Dify の `.env` で公開ポートを変更した。

```
EXPOSE_NGINX_PORT=8080
EXPOSE_NGINX_SSL_PORT=8443
```

nginx だけ再起動すれば済んだ（他13コンテナは正常に起動していた）。

```bash
docker compose up -d nginx
```

**Docker Compose は失敗したサービスだけ起動し直せる。** 全体を落として作り直す必要はない。

## 他人の環境に納品するときの含意

- **80番は最も衝突しやすいポート。** 開発者の Mac では何かが使っていることが多い
  （Apache、別の Docker、開発サーバ等）。
- セットアップ手順書に「ポートが衝突した場合の変更手順」を最初から書く。
  衝突は例外ではなく通常。
- 手順書に書く確認コマンドは、**sudo を要求しないもの**を選ぶ。
  sudo が必要な手順は、権限のない利用者のところで止まる。

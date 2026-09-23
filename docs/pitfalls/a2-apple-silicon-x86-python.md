# Apple Silicon なのに x86_64 の Python が選ばれ、arm64 専用パッケージが入らない

- **ブロック：** A-2
- **日付：** 2026-09-01
- **一般性：** Homebrew を Intel 時代から使い続けている macOS 環境なら誰でも
- **溶かした時間：** 約 0.2 時間

## 現象

`sentence-transformers`（torch 依存）のインストールが失敗する。

```
error: Distribution `torch==2.14.0` can't be installed because it doesn't have
a source distribution or wheel for the current platform

hint: You're on macOS (`macosx_26_0_x86_64`), but `torch` only has wheels for:
`manylinux_2_28_aarch64`, `manylinux_2_28_x86_64`, `macosx_14_0_arm64`, `win_amd64`
```

**ハードウェアは Apple M4（arm64）なのに、`macosx_26_0_x86_64` と判定されている。**

## 原因

仮想環境の Python が **x86_64 ビルド**だった。

```bash
$ readlink -f .venv/bin/python3
/usr/local/Cellar/python@3.11/3.11.13/.../bin/python3.11

$ file .venv/bin/python3
Mach-O 64-bit executable x86_64      # ← ハードウェアは arm64
```

`/usr/local/` は **Intel 版 Homebrew** のパス（Apple Silicon 版は `/opt/homebrew/`）。
Intel Mac から移行した環境では両方が残り、`uv venv --python 3.11` のような
バージョン指定だけでは**どちらが選ばれるか分からない。**

Rosetta で動いているわけではない（`sysctl.proc_translated` は 0）。
**arm64 のマシン上で、x86_64 のバイナリが素直に動いている**状態。
普通のライブラリなら気づかないまま動き続ける。

## なぜ気づきにくいか

- Python は普通に動く。エラーも出ない
- `uname -m` は `arm64` を返す（ハードウェアの話なので）
- システム Python（`/usr/bin/python3`）も arm64 を返す
- **仮想環境の中だけが x86_64**

**arm64 wheel しか無いパッケージを入れようとして初めて露見する。**
torch のように arm64 専用ビルドが主流のものでしか起きない。

## 対処

Python を**バージョンではなく実装で指定する。**

```bash
uv python list                    # 使える Python とアーキテクチャを一覧
uv venv --python cpython-3.13.11-macos-aarch64-none --allow-existing
uv run python -c "import platform; print(platform.machine())"   # → arm64
```

### 確認手順（次から最初にやる）

```bash
uv run python -c "import platform; print(platform.machine())"
file .venv/bin/python3
```

**環境を作った直後にアーキテクチャを確認する。**
パッケージを入れる段階で気づくと、依存解決のエラーメッセージから
原因を逆算することになり遠回りになる。

## 他人の環境に納品するときの含意

- **「同じ macOS」でも Python のアーキテクチャは揃っていない。**
  Intel から移行した環境には x86_64 の Homebrew が残っている。
- セットアップ手順書には「Python 3.11 以上」ではなく、
  **アーキテクチャの確認コマンドと期待される出力**を書く。
- A-1 の nodenv の件（→ [記録](a1-clasp-nodenv-rehash.md)）と同じ構造。
  **バージョンマネージャや複数インストールの共存は、
  「どれが使われているか」を明示的に確認しないと事故る。**
- ローカルで機械学習モデルを動かす構成を納品するなら、
  この確認をセットアップの最初のステップに入れる。

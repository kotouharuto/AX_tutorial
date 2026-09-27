"""標準出力・標準エラー出力を UTF-8 に固定する。

【なぜ必要か】Windows の Python は stdout のエンコーディングを **OS のロケール**から決める。
そのため同じコードが環境によって次のように分かれる:

    macOS / Linux              UTF-8   日本語を印字できる
    日本語 Windows のコンソール  cp932   日本語を印字できる（＝手で動かすと問題が出ない）
    英語ロケールの Windows / CI  cp1252  日本語を1文字も印字できず UnicodeEncodeError で落ちる

つまり「顧客が日本語 Windows で手動実行すると動くのに、タスクスケジューラ経由や
出力のリダイレクト、英語環境だと落ちる」という形で表面化する。
GitHub Actions の windows-latest（en-US）で実際に落ちたのがこれ。

【なぜ環境変数（PYTHONUTF8 / PYTHONIOENCODING）ではなくコード側で行うか】
環境変数はワークフローや起動スクリプトの設定でしかなく、**配布先には付いていかない**。
CI を緑にするだけで顧客環境の不具合は残るため、コードに同梱する方法を採る。

【errors="replace" にする理由】印字はあくまで進捗表示であり、成果物はすべて
encoding を明示してファイルへ書いている。表示できない文字が混じったとき、
バッチ全体を落とすより印字を諦める方が損失が小さい。
"""

import sys
from typing import IO


def force_utf8_stdio() -> None:
    """stdout / stderr を UTF-8 に再設定する。エントリポイントの冒頭で呼ぶ。"""
    for stream in (sys.stdout, sys.stderr):
        # パイプやリダイレクト先が TextIOWrapper でない場合（テストの capsys 等）は
        # reconfigure を持たないため、黙って飛ばす。ここで落とす価値はない。
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def stdio_encodings() -> dict[str, str | None]:
    """現在の stdout / stderr のエンコーディングを返す。環境差の切り分けを記録に残すために使う。"""
    def enc(stream: IO[str]) -> str | None:
        return getattr(stream, "encoding", None)

    return {"stdout": enc(sys.stdout), "stderr": enc(sys.stderr)}

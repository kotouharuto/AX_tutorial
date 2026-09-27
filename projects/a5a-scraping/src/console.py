"""標準出力を UTF-8 に固定する。

【なぜ A-4 と重複しているか】`projects/*` は独立して動かせる単位にする規約のため、
プロジェクト間で import しない。意図的な重複。

【なぜ必要か】Windows の Python は stdout のエンコーディングを OS のロケールから決めるため、
英語ロケールでは日本語を1文字も印字できずに落ちる。
A-5a は定期実行（コンソールのない経路）が到達条件に入っているので、必ず踏む。
詳細：docs/pitfalls/a4-windows-stdout-encoding.md
"""

import sys


def force_utf8_stdio() -> None:
    """stdout / stderr を UTF-8 に再設定する。エントリポイントの冒頭で呼ぶ。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

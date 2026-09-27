"""対象サイトの robots.txt とアクセス条件を確認する。**取得より先に実行する。**

【なぜ最初にやるか】受注判断の材料そのものだから。
技術的に取得できるかと、取得してよいかは別の問題であり、
後者を確認しないまま実装を進めると、成果物ごと使えなくなる。

標準ライブラリだけで書いてある。依存を入れる前に実行できるようにするため。
"""

import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

# 練習用サイトのみ。これ以外を追加するときは必ず承認を得る（plan.md の制約）。
TARGETS = (
    "https://books.toscrape.com/",
    "https://quotes.toscrape.com/",
    "https://quotes.toscrape.com/js/",
)
USER_AGENT = "ax-tutorial-a5a/0.1 (learning exercise)"
TIMEOUT = 15


def fetch_robots_text(origin: str) -> str | None:
    """robots.txt の本文を取得する。無い場合は None を返す。"""
    url = f"{origin}/robots.txt"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            # robots.txt は仕様上 UTF-8。壊れた文字があっても判断を止めない。
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        # 404 以外は「確認できなかった」であって「許可されている」ではない。区別する。
        raise
    return None


def main() -> int:
    """各対象について robots.txt の内容と可否を表示する。"""
    force_utf8_stdio()

    origins = sorted({f"{u.split('/')[0]}//{u.split('/')[2]}" for u in TARGETS})
    for origin in origins:
        print(f"=== {origin}/robots.txt ===")
        text = fetch_robots_text(origin)
        if text is None:
            # robots.txt が無いことは「全面許可」を意味しない。利用規約の確認が別に必要。
            print("  robots.txt が存在しない（404）")
            print("  → 全面許可の意味ではない。利用規約を別途確認する")
        else:
            body = text.strip()
            print(body if body else "  （空）")
        print()

    print("=== 各 URL の可否（User-agent 別）===")
    # 【重要】can_fetch が True を返す理由は2通りあり、意味が違う。
    #   (a) robots.txt に許可が書かれている
    #   (b) robots.txt が無い（404）ので、慣習上 allow-all として扱われている
    # (b) は「確認した結果の許可」ではなく「規定が無い」だけ。表示で区別する。
    for origin in origins:
        has_robots = fetch_robots_text(origin) is not None
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            parser.read()
        except Exception as exc:  # noqa: BLE001
            # 読めなかったことを許可として扱わない。
            # なお RobotFileParser は read() 失敗時 can_fetch=False を返す（fail-closed）。
            print(f"  {origin}: robots.txt を読めなかった（{exc}）→ 禁止扱いで進める")
            continue
        for url in TARGETS:
            if not url.startswith(origin):
                continue
            for agent in (USER_AGENT, "*"):
                allowed = parser.can_fetch(agent, url)
                if not allowed:
                    mark = "**禁止**"
                elif has_robots:
                    mark = "許可（明示）"
                else:
                    mark = "許可（robots.txt なし・規定がないだけ）"
                print(f"  {mark}  {url}  (UA={agent})")
        delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
        print(f"  Crawl-delay の指定: {delay if delay is not None else 'なし'}")

    print()
    print("注意：")
    print("  - Crawl-delay の指定が無くても間隔を空ける。指定なし＝無制限ではない")
    print("  - robots.txt が無いことは許可の根拠にならない。利用規約の確認が別に必要")
    print("  - robots.txt を読めなかったときは禁止として扱う（確認できない＝許可ではない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

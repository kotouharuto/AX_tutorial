"""JS 描画ページを3つの方式で取得し、所要時間を比べる。

方式:
    static   requests のみ（比較用。0件になることの再確認）
    inline   <script> の var data = [...] を直接読む（ブラウザ不要）
    browser  Playwright でブラウザに描画させる

【なぜ inline を比べるか】ハマりポイント30件目に
「script の JSON を読む方が速い」と書いたので、**実測で裏を取る。**
書いたまま検証しないと、A-2 で踏んだ「評価する側が間違っていた」と同じことになる。
"""

import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

START_URL = "https://quotes.toscrape.com/js/"
USER_AGENT = "ax-tutorial-a5a/0.1 (learning exercise)"
REQUEST_INTERVAL = 1.0
TIMEOUT = 15
MAX_PAGES = 100

# var data = [ ... ]; を取り出す。非貪欲にして次の文を巻き込まない。
INLINE_DATA_RE = re.compile(r"var\s+data\s*=\s*(\[.*?\]);", re.S)


@dataclass
class Quote:
    """1件の引用。3方式で同じ形に落として比較できるようにする。"""

    text: str
    author: str
    tags: list[str]


def _next_url(html: str, current: str) -> str | None:
    """ページ送りのリンクを返す。**静的 HTML に存在する**ことが観察の要点。"""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("li.next > a")
    if link and link.get("href"):
        return urljoin(current, link["href"])
    return None


def scrape_static(session: requests.Session) -> tuple[list[Quote], int]:
    """div.quote を探す。JS 描画ページでは0件になる。"""
    quotes: list[Quote] = []
    url: str | None = START_URL
    pages = 0
    while url and pages < MAX_PAGES:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        html = response.text
        pages += 1
        soup = BeautifulSoup(html, "html.parser")
        for div in soup.select("div.quote"):
            text = div.select_one("span.text")
            author = div.select_one("small.author")
            quotes.append(
                Quote(
                    text=text.get_text(strip=True) if text else "",
                    author=author.get_text(strip=True) if author else "",
                    tags=[a.get_text(strip=True) for a in div.select("a.tag")],
                )
            )
        url = _next_url(html, url)
        if url:
            time.sleep(REQUEST_INTERVAL)
    return quotes, pages


def scrape_inline(session: requests.Session) -> tuple[list[Quote], int]:
    """<script> の var data を読む。ブラウザを起動しない。"""
    quotes: list[Quote] = []
    url: str | None = START_URL
    pages = 0
    while url and pages < MAX_PAGES:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        html = response.text
        pages += 1

        match = INLINE_DATA_RE.search(html)
        if match is None:
            # 見つからないことを0件として黙って流さない。方式の前提が崩れている。
            raise RuntimeError(f"var data が見つからない: {url}")
        # JS のリテラルだが、このサイトは JSON として解釈できる形だった。
        # 一般には末尾カンマや単引用符で失敗するので、失敗を検知できる形にしておく。
        try:
            rows = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"var data を JSON として解釈できない: {url}") from exc

        for row in rows:
            quotes.append(
                Quote(
                    text=row.get("text", ""),
                    author=(row.get("author") or {}).get("name", ""),
                    tags=list(row.get("tags", [])),
                )
            )
        url = _next_url(html, url)
        if url:
            time.sleep(REQUEST_INTERVAL)
    return quotes, pages


def scrape_browser() -> tuple[list[Quote], int]:
    """Playwright でブラウザに描画させてから読む。"""
    from playwright.sync_api import sync_playwright

    quotes: list[Quote] = []
    pages = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            url: str | None = START_URL
            while url and pages < MAX_PAGES:
                page.goto(url, timeout=TIMEOUT * 1000)
                # 描画を待つ。**固定の sleep ではなく要素の出現を待つ。**
                # sleep だと遅い環境で0件になり、しかも例外が出ない。
                page.wait_for_selector("div.quote", timeout=TIMEOUT * 1000)
                pages += 1
                for div in page.query_selector_all("div.quote"):
                    text = div.query_selector("span.text")
                    author = div.query_selector("small.author")
                    quotes.append(
                        Quote(
                            text=text.inner_text().strip() if text else "",
                            author=author.inner_text().strip() if author else "",
                            tags=[t.inner_text().strip() for t in div.query_selector_all("a.tag")],
                        )
                    )
                next_link = page.query_selector("li.next > a")
                url = urljoin(url, next_link.get_attribute("href")) if next_link else None
                if url:
                    time.sleep(REQUEST_INTERVAL)
        finally:
            browser.close()
    return quotes, pages


def save(name: str, quotes: list[Quote]) -> Path:
    """結果を JSON で残す。件数だけでなく中身を確認できるようにする。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.json"
    path.write_text(
        json.dumps([asdict(q) for q in quotes], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def main() -> int:
    """3方式を順に実行し、件数と所要時間を並べる。"""
    force_utf8_stdio()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    results: dict[str, tuple[int, int, float]] = {}

    for name, runner in (
        ("static", lambda: scrape_static(session)),
        ("inline", lambda: scrape_inline(session)),
        ("browser", scrape_browser),
    ):
        print(f"=== {name} ===")
        started = time.time()
        quotes, pages = runner()
        elapsed = time.time() - started
        results[name] = (len(quotes), pages, elapsed)

        path = save(f"js_{name}", quotes)
        print(f"  ページ {pages} / 取得 {len(quotes)} 件 / {elapsed:.1f} 秒 → {path.name}")
        if quotes:
            print(f"  先頭: {quotes[0].author} / {quotes[0].text[:40]}")
        print()

    print("=== 比較 ===")
    print(f"{'方式':<10} {'件数':>6} {'ページ':>6} {'所要秒':>8} {'待ち時間を除く':>14}")
    print("-" * 50)
    for name, (count, pages, elapsed) in results.items():
        # アクセス間隔の待ち時間は方式によらず同じなので、除いた値も出す。
        waiting = max(pages - 1, 0) * REQUEST_INTERVAL
        print(f"{name:<10} {count:>6} {pages:>6} {elapsed:>8.1f} {elapsed - waiting:>14.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

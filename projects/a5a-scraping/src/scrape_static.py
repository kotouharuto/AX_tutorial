"""静的ページを取得する（requests + BeautifulSoup）。**まず素朴に書く。**

対象：
    books.toscrape.com    サーバ側で HTML が組み立てられる（静的）
    quotes.toscrape.com/js/  JavaScript で描画される

**同じコードで両方を取りに行く。** JS 描画ページで何が返るかを見るのが目的。
"""

import json
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

USER_AGENT = "ax-tutorial-a5a/0.1 (learning exercise)"
# robots.txt に Crawl-delay の指定は無かったが、1秒以上空ける（plan.md の制約）。
# 「指定が無い＝無制限」ではない。
REQUEST_INTERVAL = 1.0
TIMEOUT = 15


@dataclass
class Item:
    """取得した1件。サイトが違っても同じ形に落とす。"""

    title: str
    detail: str
    source_url: str


def fetch(url: str, session: requests.Session) -> str:
    """1ページ取得する。HTTP エラーは黙って進めず例外にする。"""
    response = session.get(url, timeout=TIMEOUT)
    # 404 のページを「空の結果」として扱うと、0件の原因が分からなくなる。
    response.raise_for_status()
    # requests の既定は Content-Type 依存の推測。明示して文字化けの余地を消す。
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def parse_books(html: str, page_url: str) -> list[Item]:
    """books.toscrape.com の一覧から書名と価格を取る。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    for article in soup.select("article.product_pod"):
        link = article.select_one("h3 > a")
        price = article.select_one("p.price_color")
        items.append(
            Item(
                # title 属性に完全な書名が入っている（テキストは省略される）
                title=(link.get("title") or link.get_text(strip=True)) if link else "",
                detail=price.get_text(strip=True) if price else "",
                source_url=page_url,
            )
        )
    return items


def parse_quotes(html: str, page_url: str) -> list[Item]:
    """quotes.toscrape.com の一覧から引用と著者を取る。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    for div in soup.select("div.quote"):
        text = div.select_one("span.text")
        author = div.select_one("small.author")
        items.append(
            Item(
                title=text.get_text(strip=True) if text else "",
                detail=author.get_text(strip=True) if author else "",
                source_url=page_url,
            )
        )
    return items


def crawl(start_url: str, parser, next_selector: str, max_pages: int = 100) -> list[Item]:
    """次ページを辿って全件集める。取得間隔を必ず空ける。"""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    items: list[Item] = []
    url = start_url
    pages = 0
    page_times: list[float] = []

    while url and pages < max_pages:
        started = time.time()
        html = fetch(url, session)
        page_times.append(time.time() - started)
        pages += 1

        items.extend(parser(html, url))

        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.select_one(next_selector)
        next_url = urljoin(url, next_link["href"]) if next_link and next_link.get("href") else None
        url = next_url

        if url:
            time.sleep(REQUEST_INTERVAL)

    avg = sum(page_times) / len(page_times) if page_times else 0.0
    print(f"  ページ数: {pages} / 取得 {len(items)} 件 / 1ページ平均 {avg:.2f} 秒")
    return items


def save(name: str, items: list[Item]) -> Path:
    """結果を JSON で残す。**件数だけでなく中身を確認できるようにする。**"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.json"
    payload = [asdict(item) for item in items]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    """books と quotes（通常版・JS版）を同じ静的手法で取得する。"""
    force_utf8_stdio()
    total_started = time.time()

    targets = [
        ("books", "https://books.toscrape.com/", parse_books, "li.next > a"),
        ("quotes", "https://quotes.toscrape.com/", parse_quotes, "li.next > a"),
        ("quotes_js", "https://quotes.toscrape.com/js/", parse_quotes, "li.next > a"),
    ]

    for name, url, parser, next_selector in targets:
        print(f"=== {name}: {url} ===")
        items = crawl(url, parser, next_selector)
        path = save(name, items)
        print(f"  → {path.name}")
        if items:
            print(f"  先頭: {items[0].title[:40]} / {items[0].detail}")
        print()

    print(f"=== 完了（{time.time() - total_started:.1f} 秒） ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

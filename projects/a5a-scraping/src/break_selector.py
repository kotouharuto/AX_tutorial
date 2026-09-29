"""セレクタが合わなくなったときの挙動を観察する。**対処を入れる前に実行する。**

サイト側の改修でクラス名が変わることは実際に起きる。
そのとき素朴な実装がどう振る舞うかを、先に見ておく。

【観察したいこと】
- 例外が出るか、0件で正常終了するか
- 差分検出と組み合わせたとき「差分なし」と報告されるか
"""

import json
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
USER_AGENT = "ax-tutorial-a5a/0.1 (learning exercise)"
TIMEOUT = 15

# 正しいセレクタと、サイト改修を模して壊したセレクタ。
# 「クラス名が変わった」「階層が1段増えた」の2パターンを試す。
SELECTOR_CASES = (
    ("正しい", "article.product_pod", "h3 > a", "p.price_color"),
    ("クラス名が変わった", "article.product-pod", "h3 > a", "p.price_color"),
    ("階層が1段増えた", "article.product_pod", "div > h3 > a", "p.price_color"),
    ("価格だけ変わった", "article.product_pod", "h3 > a", "p.price"),
)


def scrape_with(html: str, container: str, title_sel: str, price_sel: str) -> list[dict]:
    """指定のセレクタで抽出する。**例外を握り潰さない素朴な実装のまま。**"""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    for article in soup.select(container):
        link = article.select_one(title_sel)
        price = article.select_one(price_sel)
        rows.append(
            {
                "title": (link.get("title") or link.get_text(strip=True)) if link else "",
                "price": price.get_text(strip=True) if price else "",
            }
        )
    return rows


def main() -> int:
    """4通りのセレクタで同じ HTML を処理し、結果を並べる。"""
    force_utf8_stdio()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = session.get("https://books.toscrape.com/", timeout=TIMEOUT)
    response.raise_for_status()
    html = response.text

    print(f"取得した HTML: {len(html)} bytes\n")
    print(f"{'ケース':<20} {'件数':>6}  {'書名が空':>8}  {'価格が空':>8}  例外")
    print("-" * 64)

    results: dict[str, list[dict]] = {}
    for label, container, title_sel, price_sel in SELECTOR_CASES:
        try:
            rows = scrape_with(html, container, title_sel, price_sel)
            exc = "なし"
        except Exception as e:  # noqa: BLE001
            rows, exc = [], f"{type(e).__name__}"
        results[label] = rows
        empty_title = sum(1 for r in rows if not r["title"])
        empty_price = sum(1 for r in rows if not r["price"])
        print(f"{label:<20} {len(rows):>6}  {empty_title:>8}  {empty_price:>8}  {exc}")

    # 差分検出と組み合わせたときにどう見えるかを確かめる。
    # 「前回＝正しい結果」「今回＝壊れた結果」として比較する。
    print("\n=== 差分検出と組み合わせた場合 ===")
    baseline = {r["title"] for r in results["正しい"] if r["title"]}
    for label, rows in results.items():
        if label == "正しい":
            continue
        current = {r["title"] for r in rows if r["title"]}
        added = current - baseline
        removed = baseline - current
        # 素朴な差分通知は「追加された分だけ」を知らせる実装になりがち。
        verdict = "差分なし（＝通知されない）" if not added else f"追加 {len(added)} 件"
        print(f"  {label:<20} 追加 {len(added):>4} / 削除 {len(removed):>4}  → {verdict}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "break_selector.json"
    path.write_text(
        json.dumps({k: len(v) for k, v in results.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n件数の記録 → {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""定期実行の入口。取得 → 異常判定 → 差分 → 通知 を1回分実行する。

【終了コードの設計】launchd から呼ばれるので、コードで状態を区別できるようにする。
    0  正常・差分なし
    1  **異常**（0件・急減・フィールドが空）
    2  正常・差分あり（通知した）
    3  実行そのものが失敗（取得に失敗、設定不正など）

【なぜ異常と差分を分けるか】差分検出は「変化を見つける」仕組みであって
「壊れを見つける」仕組みではない。セレクタが壊れると差分が出なくなるため、
**差分の有無で健全性を判断できない**（→ a5a-selector-break-is-silent.md）。

【launchd で動かす前提】コンソールがなく、PATH も cwd も対話シェルと違う。
    - パスはすべて __file__ 起点の絶対パス（cwd に依存しない）
    - 標準出力は UTF-8 に固定（console.py）
    - ログはファイルに残す（画面が無いので、出力先がないと何も分からない）
"""

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402
from diff import compute_diff, format_diff, load_snapshot, save_snapshot  # noqa: E402
from notify import NotifyConfigError, load_config, send  # noqa: E402
from scrape_static import USER_AGENT, crawl, parse_books, parse_quotes  # noqa: E402
from validate import format_report, load_state, save_state, validate  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_PATH = OUTPUT_DIR / "run.log"

EXIT_OK = 0
EXIT_ANOMALY = 1
EXIT_CHANGED = 2
EXIT_FAILED = 3


@dataclass(frozen=True)
class Target:
    """監視対象1件。"""

    name: str
    url: str
    parser: object
    next_selector: str
    key: str
    required_fields: tuple[str, ...]


# books は1000件あり1回50秒かかるので、定期実行の既定は quotes だけにする。
# 「全部見る」を既定にすると、頻度を上げられなくなる。
TARGETS = {
    "quotes": Target(
        name="quotes",
        url="https://quotes.toscrape.com/",
        parser=parse_quotes,
        next_selector="li.next > a",
        key="title",
        required_fields=("title", "detail"),
    ),
    "books": Target(
        name="books",
        url="https://books.toscrape.com/",
        parser=parse_books,
        next_selector="li.next > a",
        key="title",
        required_fields=("title", "detail"),
    ),
}


def log(message: str) -> None:
    """標準出力とファイルの両方に出す。**launchd では画面が無い。**"""
    stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(stamped)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(stamped + "\n")


def run_target(target: Target, dry_run: bool) -> int:
    """1件分を実行し、終了コードを返す。"""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    started = time.time()
    items = [
        {"title": i.title, "detail": i.detail, "source_url": i.source_url}
        for i in crawl(target.url, target.parser, target.next_selector)
    ]
    elapsed = time.time() - started
    log(f"[{target.name}] 取得 {len(items)} 件 / {elapsed:.1f} 秒")

    # 1) 異常判定を**先に**行う。壊れた結果で差分を取っても意味がない。
    state = load_state()
    report = validate(
        dataset=target.name,
        items=items,
        required_fields=target.required_fields,
        previous_count=state.get(target.name),
    )
    log(format_report(report))

    if not report.ok:
        body = format_report(report) + "\n\n※ 異常のため差分は取らず、基準値も更新しない。"
        _notify(f"[A-5a] 異常：{target.name}", body, dry_run)
        # 異常値を基準にすると次回から急減判定が効かなくなる（→ validate.py）
        return EXIT_ANOMALY

    # 2) 差分を取る
    result = compute_diff(target.name, items, load_snapshot(target.name), target.key)
    log(format_diff(result))

    # 3) 正常だったので基準値とスナップショットを更新する。
    #    **dry-run では一切書かない。** 書いてしまうと、次回の実行が
    #    「前回＝dry-run の結果」を基準にしてしまい、動作確認が本番に影響する。
    if dry_run:
        log("  dry-run：基準値・スナップショットは更新しない")
    else:
        state[target.name] = len(items)
        save_state(state)
        save_snapshot(target.name, items)

    if result.is_first_run:
        log("  初回のため通知しない")
        return EXIT_OK
    if not result.has_changes:
        # **差分がないことを通知しない。** 毎回メールが来ると読まれなくなる。
        log("  差分なしのため通知しない")
        return EXIT_OK

    _notify(f"[A-5a] 差分：{target.name}", format_diff(result), dry_run)
    return EXIT_CHANGED


def _notify(subject: str, body: str, dry_run: bool) -> None:
    """通知する。dry-run では送らない。"""
    if dry_run:
        log(f"  dry-run：通知しない（件名: {subject}）")
        return
    config = load_config()
    sent = send(config, subject, body)
    log(f"  通知: {'送信した' if sent else '未送信（NOTIFY_ENABLED=false）'}")


def main() -> int:
    """引数で対象を選んで実行する。"""
    force_utf8_stdio()

    parser = argparse.ArgumentParser(description="取得・判定・差分・通知を1回実行する")
    parser.add_argument("--target", default="quotes", choices=sorted(TARGETS))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="通知もスナップショット更新も行わない（動作確認用）",
    )
    args = parser.parse_args()

    log(f"=== 開始: {args.target}{' (dry-run)' if args.dry_run else ''} ===")
    try:
        code = run_target(TARGETS[args.target], args.dry_run)
    except NotifyConfigError as exc:
        # 設定不正は「通知できていない」ので、**画面に出すだけでは足りない**。
        log(f"通知設定の不正: {exc}")
        return EXIT_FAILED
    except Exception:  # noqa: BLE001
        # 握り潰さない。launchd では画面が無いので、必ずログに残す。
        log("実行に失敗した:\n" + traceback.format_exc())
        return EXIT_FAILED

    log(f"=== 終了: コード {code} ===")
    return code


if __name__ == "__main__":
    sys.exit(main())

"""取得結果が異常でないかを判定する。**0件や空欄を成功として扱わない。**

【なぜ件数だけでは足りないか】セレクタ破壊の実験（`break_selector.py`）で、
同じ HTML に対して壊れ方が3通りに分かれた。

    クラス名が変わった   →  0件               件数で検出できる
    階層が1段増えた      →  20件・書名が全部空  **件数では検出できない**
    価格だけ変わった      →  20件・価格が全部空  **件数でも差分でも検出できない**

3件とも例外は出ず、差分検出は「差分なし」と報告した。
そのため件数と**フィールドごとの空率**の両方を見る。
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
STATE_PATH = OUTPUT_DIR / "state.json"

# 【閾値の根拠】
# 空率：セレクタが合っていれば必須フィールドが空になることは原則ない。
#   ただし1件だけ欠けるサイト側の事情はあり得るので、0 ではなく 5% を既定にする。
#   「階層が1段増えた」ケースは空率100%なので、この閾値でも確実に捕まる。
# 急減：前回比で半分を下回ったら異常とする。ページ送りが途中で切れたときに効く。
#   サイトの正常な減少（商品の入れ替え）で誤検知しうるので、閾値は呼び出し側で上書きできる。
DEFAULT_MAX_EMPTY_RATE = 0.05
DEFAULT_MIN_RATIO_VS_PREVIOUS = 0.5


@dataclass
class ValidationReport:
    """判定結果。**異常の内容を呼び出し側に見せる**ために理由を持つ。"""

    dataset: str
    count: int
    previous_count: int | None = None
    empty_rates: dict[str, float] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """異常がなければ True。"""
        return not self.problems


def empty_rate(items: list[dict], name: str) -> float:
    """フィールドが空である割合を返す。空文字・None・空リストを空とみなす。"""
    if not items:
        return 0.0
    empty = 0
    for item in items:
        value = item.get(name)
        # 0 や False を空扱いしない。文字列・リストの空だけを空とする。
        if value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
            empty += 1
    return empty / len(items)


def validate(
    dataset: str,
    items: list[dict],
    required_fields: tuple[str, ...],
    previous_count: int | None = None,
    max_empty_rate: float = DEFAULT_MAX_EMPTY_RATE,
    min_ratio_vs_previous: float = DEFAULT_MIN_RATIO_VS_PREVIOUS,
) -> ValidationReport:
    """件数とフィールドの空率を判定する。"""
    report = ValidationReport(dataset=dataset, count=len(items), previous_count=previous_count)

    # 1) 0件は常に異常。「サイトが空だった」と「取得に失敗した」を区別できないため、
    #    正常として通さずに人に判断させる。
    if not items:
        report.problems.append("取得件数が0件")

    # 2) 前回との急減。前回が無い初回は判定できない（異常でもない）。
    #    判定できなかったことは format_report で明示する。黙って合格にしない。
    if previous_count is not None and previous_count > 0 and (
        len(items) < previous_count * min_ratio_vs_previous
    ):
        report.problems.append(
            f"件数が急減：前回 {previous_count} 件 → 今回 {len(items)} 件"
            f"（{len(items) / previous_count:.0%}）"
        )

    # 3) 必須フィールドの空率。件数が正常でも中身が空になる壊れ方を捕まえる。
    for name in required_fields:
        rate = empty_rate(items, name)
        report.empty_rates[name] = rate
        if not items or rate <= max_empty_rate:
            continue
        # 「フィールドが存在しない」と「存在するが空」を区別する。
        # 前者は指定ミス（フィールド名の打ち間違い）、後者はセレクタ破壊であり、
        # 対処が全く違う。同じ文言で報告すると原因の切り分けに時間を使う。
        if all(name not in item for item in items):
            available = sorted({k for item in items for k in item})
            report.problems.append(
                f"{name} というフィールドが存在しない（実際のキー: {', '.join(available)}）"
            )
        else:
            report.problems.append(f"{name} が空の割合 {rate:.0%}（閾値 {max_empty_rate:.0%}）")

    return report


def load_state(path: Path = STATE_PATH) -> dict[str, int]:
    """前回の件数を読む。無ければ空。壊れていたら例外にする（推測で進めない）。"""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.items()}


def save_state(state: dict[str, int], path: Path = STATE_PATH) -> None:
    """今回の件数を保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def format_report(report: ValidationReport) -> str:
    """人が読む形にする。**異常なしの場合も判定内容を見せる。**"""
    lines = [f"[{report.dataset}] {report.count} 件"]
    if report.previous_count is None:
        lines.append("  前回比：判定できない（前回の記録がない）")
    else:
        lines.append(f"  前回比：{report.previous_count} 件 → {report.count} 件")
    for name, rate in report.empty_rates.items():
        lines.append(f"  {name} が空：{rate:.0%}")
    if report.ok:
        lines.append("  判定：異常なし")
    else:
        lines.append("  判定：**異常**")
        lines += [f"    - {p}" for p in report.problems]
    return "\n".join(lines)


def main() -> int:
    """JSON ファイルを判定する。異常があれば終了コード 1。"""
    force_utf8_stdio()

    parser = argparse.ArgumentParser(description="取得結果の異常判定")
    parser.add_argument("path", type=Path, help="判定対象の JSON")
    parser.add_argument("--fields", required=True, help="必須フィールド（カンマ区切り）")
    parser.add_argument("--max-empty-rate", type=float, default=DEFAULT_MAX_EMPTY_RATE)
    parser.add_argument("--min-ratio", type=float, default=DEFAULT_MIN_RATIO_VS_PREVIOUS)
    parser.add_argument(
        "--update-state",
        action="store_true",
        help="判定後に件数を記録する。**異常時は記録しない**（異常値を基準にしないため）",
    )
    args = parser.parse_args()

    items = json.loads(args.path.read_text(encoding="utf-8"))
    dataset = args.path.stem
    state = load_state(STATE_PATH)

    report = validate(
        dataset=dataset,
        items=items,
        required_fields=tuple(f.strip() for f in args.fields.split(",") if f.strip()),
        previous_count=state.get(dataset),
        max_empty_rate=args.max_empty_rate,
        min_ratio_vs_previous=args.min_ratio,
    )
    print(format_report(report))

    # 異常な件数を「前回値」として記録すると、次回の急減判定が効かなくなる。
    # 例：1000件 → 0件（異常）→ 0件を基準にすると、次回0件でも急減にならない。
    if args.update_state and report.ok:
        state[dataset] = report.count
        save_state(state, STATE_PATH)
        print(f"  件数を記録した → {STATE_PATH.name}")
    elif args.update_state:
        print("  異常のため件数は記録しない（異常値を次回の基準にしないため）")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

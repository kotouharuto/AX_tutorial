"""前回の取得結果と比較し、差分だけを抜き出す。

【設計上の注意】差分検出は「変化を見つける」仕組みであって
「壊れを見つける」仕組みではない。セレクタが壊れると差分が出なくなるため、
**差分の有無で健全性を判断してはいけない**（→ a5a-selector-break-is-silent.md）。
異常判定は `validate.py` の責任として分ける。

【キーの選び方】差分の単位を決めるキーが必要。
キーに使うフィールドが壊れると「全件削除＋全件追加」に見えるので、
**最も壊れにくいフィールドを選ぶ**。ここでは呼び出し側が明示する。
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
SNAPSHOT_DIR = OUTPUT_DIR / "snapshots"


@dataclass
class DiffResult:
    """差分。**変更は「前後の値」をそのまま持つ**。何がどう変わったかを人が読むため。"""

    dataset: str
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[tuple[dict, dict]] = field(default_factory=list)
    previous_count: int | None = None
    current_count: int = 0

    @property
    def has_changes(self) -> bool:
        """差分があれば True。"""
        return bool(self.added or self.removed or self.changed)

    @property
    def is_first_run(self) -> bool:
        """前回のスナップショットが無い初回かどうか。"""
        return self.previous_count is None


def snapshot_path(dataset: str) -> Path:
    """スナップショットの置き場所。"""
    return SNAPSHOT_DIR / f"{dataset}.json"


def load_snapshot(dataset: str) -> list[dict] | None:
    """前回の結果を読む。無ければ None（0件と区別する）。"""
    path = snapshot_path(dataset)
    if not path.exists():
        return None
    # 壊れていたら例外。推測で「前回は無かった」と扱うと、全件が追加として通知される。
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(dataset: str, items: list[dict]) -> Path:
    """今回の結果を保存する。"""
    path = snapshot_path(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _index(items: list[dict], key: str) -> dict[str, dict]:
    """キーで引ける形にする。キーが空・重複する場合を黙って捨てない。"""
    indexed: dict[str, dict] = {}
    duplicates: list[str] = []
    missing = 0
    for item in items:
        value = item.get(key)
        if value is None or value == "":
            missing += 1
            continue
        k = str(value)
        if k in indexed:
            duplicates.append(k)
        indexed[k] = item
    if missing:
        # キーが取れない件は差分の対象外になる。件数が合わなくなるので黙らせない。
        print(f"  警告: キー '{key}' が空の項目が {missing} 件あり、差分対象から外れた")
    if duplicates:
        print(f"  警告: キー '{key}' が重複している項目が {len(duplicates)} 件（後者で上書き）")
    return indexed


def compute_diff(dataset: str, current: list[dict], previous: list[dict] | None, key: str) -> DiffResult:
    """前回と今回を比較する。"""
    result = DiffResult(
        dataset=dataset,
        current_count=len(current),
        previous_count=None if previous is None else len(previous),
    )
    if previous is None:
        # 初回は全件が「追加」だが、それを通知すると意味がない。
        # 呼び出し側が is_first_run で判断できるようにして、ここでは詰めない。
        return result

    now = _index(current, key)
    before = _index(previous, key)

    for k, item in now.items():
        if k not in before:
            result.added.append(item)
        elif item != before[k]:
            result.changed.append((before[k], item))
    for k, item in before.items():
        if k not in now:
            result.removed.append(item)
    return result


def format_diff(result: DiffResult, max_lines: int = 20) -> str:
    """人が読む形にする。全件を並べない（メール本文が使えなくなる）。"""
    if result.is_first_run:
        return "\n".join(
            [
                f"[{result.dataset}] 今回 {result.current_count} 件",
                "  初回のため差分なし（今回の結果を基準として保存）",
            ]
        )
    lines = [f"[{result.dataset}] 前回 {result.previous_count} 件 → 今回 {result.current_count} 件"]
    if not result.has_changes:
        lines.append("  差分なし")
        return "\n".join(lines)

    lines.append(
        f"  追加 {len(result.added)} 件 / 削除 {len(result.removed)} 件 /"
        f" 変更 {len(result.changed)} 件"
    )
    for label, rows in (("追加", result.added), ("削除", result.removed)):
        for item in rows[:max_lines]:
            lines.append(f"  [{label}] {json.dumps(item, ensure_ascii=False)[:160]}")
        if len(rows) > max_lines:
            lines.append(f"  [{label}] ...ほか {len(rows) - max_lines} 件")

    for before, after in result.changed[:max_lines]:
        # どのフィールドが変わったかだけを出す。全体を出すと読めない。
        diffs = [f"{k}: {before.get(k)!r} → {after.get(k)!r}" for k in after if before.get(k) != after.get(k)]
        lines.append(f"  [変更] {' / '.join(diffs)[:200]}")
    if len(result.changed) > max_lines:
        lines.append(f"  [変更] ...ほか {len(result.changed) - max_lines} 件")

    return "\n".join(lines)


def main() -> int:
    """JSON を前回のスナップショットと比較する。差分があれば終了コード 2。"""
    force_utf8_stdio()

    import argparse

    parser = argparse.ArgumentParser(description="前回との差分を求める")
    parser.add_argument("path", type=Path)
    parser.add_argument("--key", required=True, help="差分の単位にするフィールド")
    parser.add_argument("--save", action="store_true", help="今回の結果をスナップショットとして保存")
    args = parser.parse_args()

    items = json.loads(args.path.read_text(encoding="utf-8"))
    dataset = args.path.stem
    result = compute_diff(dataset, items, load_snapshot(dataset), args.key)
    print(format_diff(result))

    if args.save:
        path = save_snapshot(dataset, items)
        print(f"  スナップショットを保存 → {path.name}")

    # 0=差分なし、2=差分あり。異常（1）とは別の値にして呼び出し側で区別できるようにする。
    return 2 if result.has_changes else 0


if __name__ == "__main__":
    sys.exit(main())

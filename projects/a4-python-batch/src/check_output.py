"""出力ファイルが揃っているかを確認する。CI と、配布先での動作確認に使う。

【なぜスクリプトに分けたか】以前はワークフローに `python -c "..."` を直書きしていたが、
日本語のファイル名（例：`TKY_202608_報告書.pdf`）を印字するため、
英語ロケールの Windows で `UnicodeEncodeError` を起こしていた。

**ワンライナーは console.force_utf8_stdio() を通らない。**
本体を直しても、検証側の急ごしらえのコードに同じ不具合が残る。
印字する箇所はすべて同じ入口を通す。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# 対象月に依存しない部分だけを見る。件数の正しさは pytest 側の責任。
EXPECTED = ("load_report.txt", "normalized.csv")
EXPECTED_PDF_COUNT = 5


def main() -> int:
    """出力を検査する。欠けがあれば終了コードを 1 にする。"""
    force_utf8_stdio()

    if not OUTPUT_DIR.is_dir():
        # 出力ディレクトリがないのは、バッチが途中で落ちたということ。黙って0を返さない。
        print(f"エラー: 出力ディレクトリがない: {OUTPUT_DIR}", file=sys.stderr)
        return 1

    files = sorted(p for p in OUTPUT_DIR.rglob("*") if p.is_file())
    for path in files:
        print(f"{path.relative_to(OUTPUT_DIR)}  {path.stat().st_size} bytes")

    problems: list[str] = []
    names = {p.name for p in files}
    for name in EXPECTED:
        if name not in names:
            problems.append(f"出力がない: {name}")

    # サイズ0のファイルは「作られたが書けなかった」状態。成功と区別する。
    problems += [f"サイズが0: {p.name}" for p in files if p.stat().st_size == 0]

    pdfs = [p for p in files if p.suffix.lower() == ".pdf" and p.parent.name == "pdf"]
    if len(pdfs) != EXPECTED_PDF_COUNT:
        problems.append(f"個別 PDF が {len(pdfs)} 件（期待 {EXPECTED_PDF_COUNT} 件）")

    if problems:
        print("\n【異常】", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"\n確認OK: {len(files)} ファイル")
    return 0


if __name__ == "__main__":
    sys.exit(main())

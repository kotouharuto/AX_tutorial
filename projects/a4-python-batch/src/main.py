"""A-4 バッチ：支店別ファイルを結合し、報告帳票と PDF を出力する。

実行方法：
    python src/main.py

出力（すべて output/ 配下）：
    normalized.csv          正規化後の全明細。**元ファイルと突き合わせて検証するため**
    load_report.txt         読み込み内訳（何行除去したか）
    report_YYYY-MM.xlsx     書式付きの報告帳票
    pdf/{支店ID}_YYYYMM_報告書.pdf   リネーム後の個別 PDF
    merged_YYYY-MM.pdf      結合 PDF

【設計方針】中間結果を必ずファイルに残す。
集計後の数字だけを出すと、1行ごとの変換が正しいか確認できない。
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import load_all  # noqa: E402
from pdf_tasks import merge_pdfs, rename_pdfs  # noqa: E402
from report import build_crosstab, write_report  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_EXCEL = BASE_DIR / "input" / "excel"
INPUT_PDF = BASE_DIR / "input" / "pdf"
OUTPUT_DIR = BASE_DIR / "output"


def main() -> int:
    """バッチを実行する。異常があれば終了コードを 1 にする。"""
    parser = argparse.ArgumentParser(description="支店別問い合わせ集計バッチ")
    parser.add_argument("--month", default="2026-08", help="対象月（YYYY-MM）")
    args = parser.parse_args()

    year, month = (int(v) for v in args.month.split("-"))
    target_month = date(year, month, 1)

    started = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    # --- 1. 読み込みと正規化 ---
    print("=== 1. 読み込み ===")
    df, reports = load_all(INPUT_EXCEL)
    note_lines = [r.summary() for r in reports]
    for line in note_lines:
        print(f"  {line}")

    # 変換できなかった値があれば警告する。黙って捨てない。
    for r in reports:
        if r.invalid_dates:
            warnings.append(f"{r.source}: 日付を変換できない行が {len(r.invalid_dates)} 件")
        if r.invalid_counts:
            warnings.append(f"{r.source}: 件数を変換できない行が {len(r.invalid_counts)} 件")

    # --- 2. 正規化後のデータを残す（検証用） ---
    normalized_path = OUTPUT_DIR / "normalized.csv"
    df.to_csv(normalized_path, index=False, encoding="utf-8-sig")
    print(f"\n=== 2. 正規化後のデータ ===\n  {len(df)} 行 → {normalized_path.name}")
    print(f"  支店: {sorted(df['支店'].unique())}")
    print(f"  種別: {sorted(df['種別'].unique())}")

    # --- 3. 集計と帳票 ---
    table = build_crosstab(df)
    report_path = OUTPUT_DIR / f"report_{args.month}.xlsx"
    write_report(table, report_path, target_month, note_lines)
    print(f"\n=== 3. 帳票 ===\n{table.to_string()}\n  → {report_path.name}")

    # --- 4. PDF のリネームと結合 ---
    print("\n=== 4. PDF ===")
    renamed, unknown = rename_pdfs(INPUT_PDF, OUTPUT_DIR / "pdf", target_month)
    for before, after in renamed:
        print(f"  {before}  →  {after}")
    if unknown:
        warnings.append(f"支店を判定できない PDF: {', '.join(unknown)}")

    merged_path = OUTPUT_DIR / f"merged_{args.month}.pdf"
    merged = merge_pdfs(OUTPUT_DIR / "pdf", merged_path)
    print(f"  結合: {len(merged)} ファイル → {merged_path.name}")

    # --- 5. 内訳をテキストでも残す ---
    elapsed = time.time() - started
    lines = [
        f"実行日時: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"対象月: {args.month}",
        f"処理時間: {elapsed:.2f} 秒",
        f"読み込み: {len(reports)} ファイル / 明細 {len(df)} 行",
        "",
        "【ファイル別の内訳】",
        *[f"  {line}" for line in note_lines],
        "",
        "【PDF】",
        *[f"  {b} → {a}" for b, a in renamed],
    ]
    if warnings:
        lines += ["", "【警告】", *[f"  {w}" for w in warnings]]
    (OUTPUT_DIR / "load_report.txt").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n=== 完了（{elapsed:.2f} 秒） ===")
    if warnings:
        print("警告あり:")
        for w in warnings:
            print(f"  {w}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A-4 のテストデータを生成する。

**シードを固定して再現可能にする。** 生成物は .gitignore に入れ、このスクリプトだけをコミットする。

【設計方針】実務で実際に届くファイルの汚れを再現する。
綺麗なデータで動くバッチは、現場のファイルを前にして止まる。

**意図的に仕込んだ汚れは README に一覧で明記する。**
意図しない事故（文字化け・タイプミス）と区別できるようにするため（Phase A で3回発生）。
"""

import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

SEED = 20260925
OUT_DIR = Path(__file__).resolve().parent.parent / "input"

# 支店。表記ゆれを意図的に入れるため、正式名と実際の記載を分ける。
BRANCHES = [
    # (支店ID, 正式名, ファイル内の記載（ゆれを含む）)
    ("TKY", "東京", "東京"),
    ("OSK", "大阪", "大 阪"),        # 【汚れ】全角スペース混入
    ("NGO", "名古屋", "名古屋"),
    ("FUK", "福岡", "福岡"),
    ("SPR", "札幌", "札幌"),          # cp932 CSV で届く支店
]

# 問い合わせ種別。A-1 の4分類に合わせる。
CATEGORIES = ["システム障害", "申請手続き", "備品・設備", "その他"]

# 【汚れ】半角カナでの記載ゆれ。同じ「システム障害」を指す。
CATEGORY_VARIANTS = {"システム障害": "ｼｽﾃﾑ障害"}

JP_FONT = "HeiseiKakuGo-W5"


def build_rows(rng: random.Random, branch_label: str, month: date) -> list[list]:
    """1支店1ヶ月分の明細行を作る。汚れを混ぜる。"""
    rows: list[list] = []
    days = rng.randint(12, 18)

    for i in range(days):
        d = month + timedelta(days=rng.randint(0, 27))
        category = rng.choice(CATEGORIES)

        # 【汚れ1】日付の型が混在する。
        # 3件に1件は文字列で入れる（レガシーシステムからの転記を想定）。
        # openpyxl は文字列をそのまま文字列として書くため、Excel 上でも文字列になる。
        date_cell = d.strftime("%Y/%m/%d") if i % 3 == 0 else d

        # 【汚れ2】種別の表記ゆれ。5件に1件は半角カナ。
        if i % 5 == 0 and category in CATEGORY_VARIANTS:
            category = CATEGORY_VARIANTS[category]

        # 【汚れ3】件数が全角数字で入ることがある。
        count = rng.randint(1, 20)
        count_cell = str(count).translate(str.maketrans("0123456789", "０１２３４５６７８９")) if i % 7 == 0 else count

        rows.append([date_cell, branch_label, category, count_cell, f"担当{rng.randint(1, 4)}"])

        # 【汚れ4】途中に空行が入る（手作業での編集を想定）。
        if i == days // 2:
            rows.append([None, None, None, None, None])

    return rows


def write_branch_xlsx(path: Path, branch_label: str, month: date, rows: list[list]) -> None:
    """支店1ファイル分の xlsx を書く。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "集計"

    # 【汚れ5】タイトル行が結合セル。A1:E1 を結合して見出しを置く。
    # データは3行目から始まるので、素朴に read_excel すると1行目をヘッダと誤認する。
    ws.merge_cells("A1:E1")
    ws["A1"] = f"{branch_label}支店　{month.year}年{month.month}月　問い合わせ集計"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.append([])  # 2行目は空
    ws.append(["日付", "支店", "種別", "件数", "担当者"])  # 3行目がヘッダ

    for row in rows:
        ws.append(row)

    # 【汚れ6】最終行に数式で合計を入れる。
    # openpyxl が書いた数式は計算結果を持たないため、data_only=True で読むと None になる。
    # Excel で一度開いて保存すれば値がキャッシュされるが、機械生成のファイルにはそれがない。
    last = ws.max_row
    ws.append([None, None, "合計", f"=SUM(D4:D{last})", None])
    ws.cell(row=last + 1, column=3).font = Font(bold=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_branch_csv(path: Path, branch_label: str, rows: list[list]) -> None:
    """1支店分を cp932 の CSV で書く。

    【汚れ7】文字コードが cp932（Shift_JIS）。
    macOS / Linux の既定は UTF-8 なので、encoding を指定せずに読むと失敗するか文字化けする。
    レガシーな基幹システムからの出力では今も普通に起きる。
    """
    lines = ["日付,支店,種別,件数,担当者"]
    for row in rows:
        if all(v is None for v in row):
            lines.append(",,,,")  # 空行もそのまま出す
            continue
        d = row[0].strftime("%Y/%m/%d") if isinstance(row[0], date) else str(row[0])
        lines.append(f"{d},{row[1]},{row[2]},{row[3]},{row[4]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(lines).encode("cp932"))


def write_branch_pdf(path: Path, branch_label: str, month: date, total: int) -> None:
    """支店別の報告 PDF を1ページ作る。後で結合・リネームの題材にする。"""
    pdfmetrics.registerFont(UnicodeCIDFont(JP_FONT))
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont(JP_FONT, 18)
    c.drawString(60, height - 80, f"{branch_label}支店 月次報告")
    c.setFont(JP_FONT, 12)
    c.drawString(60, height - 120, f"対象月：{month.year}年{month.month}月")
    c.drawString(60, height - 150, f"問い合わせ件数：{total} 件")
    c.setFont(JP_FONT, 9)
    c.drawString(60, 60, "※ A-4 検証用の架空データです。")
    c.save()


def main() -> None:
    """入力ファイル一式を生成する。"""
    rng = random.Random(SEED)
    month = date(2026, 8, 1)

    for old in OUT_DIR.rglob("*"):
        if old.is_file():
            old.unlink()

    created: list[str] = []
    for branch_id, formal, label in BRANCHES:
        rows = build_rows(rng, label, month)
        total = sum(int(str(r[3]).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
                    for r in rows if r[3] is not None)

        if branch_id == "SPR":
            # 【汚れ7】札幌だけ cp932 の CSV で届く
            path = OUT_DIR / "excel" / f"{branch_id}_2026-08.csv"
            write_branch_csv(path, label, rows)
        else:
            path = OUT_DIR / "excel" / f"{branch_id}_2026-08.xlsx"
            write_branch_xlsx(path, label, month, rows)
        created.append(path.name)

        # 【汚れ8】PDF のファイル名が命名規則に沿っていない（支店ごとにバラバラ）
        pdf_names = {
            "TKY": "report_tokyo_202608.pdf",
            "OSK": "大阪支店 月次報告(8月).pdf",   # 日本語・スペース・括弧
            "NGO": "NGO-2026_08_report.pdf",
            "FUK": "fuk202608.pdf",
            "SPR": "札幌_報告書_最終版.pdf",        # 「最終版」
        }
        pdf_path = OUT_DIR / "pdf" / pdf_names[branch_id]
        write_branch_pdf(pdf_path, label, month, total)
        created.append(pdf_path.name)

    print(f"生成完了: {len(created)} ファイル → {OUT_DIR}")
    for name in created:
        print(f"  {name}")


if __name__ == "__main__":
    main()

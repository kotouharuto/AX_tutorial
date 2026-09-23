"""A-2 題材文書を生成する。

**シードを固定して再現可能にする。** 生成物は .gitignore に入れ、
このスクリプトだけをコミットする（評価の再現性はスクリプトが担保する）。

出力形式を分けているのは、パース品質の差を測るため。
- md       : テキストとして素直に読める
- table_pdf: 表。セル構造が壊れやすい
- scan_pdf : 画像。テキスト抽出できない
"""

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from documents import CORE_DOCS, SCAN_DOCS, TABLE_DOCS, Doc
from padding import (
    EXTRA_SECTIONS,
    PROCEDURE_APPENDIX,
    PROCEDURE_PREAMBLE,
    REGULATION_APPENDIX,
    REGULATION_PREAMBLE,
)

SEED = 20260901
OUT_DIR = Path(__file__).parent / "out"
LONG_OUT_DIR = Path(__file__).parent / "out_long"

# reportlab 内蔵の日本語 CID フォント。追加のフォントファイルを持たなくて済む。
JP_FONT = "HeiseiKakuGo-W5"

# 画像PDF用。macOS 標準フォントを使う（日本語を画像に描くために必要）。
SCAN_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


# ---------------------------------------------------------------------------
# 表データ（意図的に壊れやすい構造にしてある）
# ---------------------------------------------------------------------------

TABLE_DATA: dict[str, list[list[str]]] = {
    # 結合セルを模した表。地域区分が階層になっており、空セルが上の値を引き継ぐ。
    # 素直に1行ずつ読むと、空セルの行が何の地域か分からなくなる。
    "TBL-501": [
        ["経費区分", "地域区分", "上限額", "備考"],
        ["宿泊費", "首都圏", "15,000円", "東京・神奈川・千葉・埼玉"],
        ["", "その他地域", "12,000円", ""],
        ["", "海外", "別途協議", "海外渡航申請が必要"],
        ["日当", "国内", "2,000円", "1泊につき"],
        ["", "海外", "5,000円", ""],
        ["交通費", "全地域", "実費", "上限なし"],
        ["接待費", "全地域", "8,000円", "1名あたり。事前承認必須"],
    ],
    # ヘッダが2行にまたがる。1行目だけをヘッダとして読むと列の意味が失われる。
    "TBL-502": [
        ["申請種別", "金額帯", "", "", ""],
        ["", "5万円未満", "5万〜20万円", "20万〜100万円", "100万円以上"],
        ["経費精算", "所属長", "部門長", "担当役員", "社長"],
        ["備品購入", "所属長", "所属長＋総務", "担当役員", "社長"],
        ["外注費", "部門長", "部門長", "担当役員", "取締役会"],
        ["出張", "所属長", "部門長", "担当役員", "－"],
    ],
    # 同一品目が型番違いで複数行。納期の単位が混在している。
    "TBL-503": [
        ["品目", "型番", "単価", "納期"],
        ["ノートPC", "NB-1400", "138,000円", "10営業日"],
        ["ノートPC", "NB-1400S", "162,000円", "3週間"],
        ["モニタ 24型", "MN-2401", "28,000円", "5営業日"],
        ["モニタ 27型", "MN-2701", "42,000円", "5営業日"],
        ["ドッキングステーション", "DS-300", "19,800円", "2週間"],
        ["Webカメラ", "WC-100", "8,900円", "3営業日"],
        ["ヘッドセット", "HS-220", "12,400円", "3営業日"],
    ],
}


# ---------------------------------------------------------------------------
# ノイズ文書（テンプレート生成）
# ---------------------------------------------------------------------------

DEPARTMENTS = ["営業部", "情報システム部", "総務部", "経理部", "AX推進部", "人事部"]
TOPICS = [
    "月次進捗の共有",
    "新システム導入の検討",
    "年度予算の確認",
    "業務フロー見直し",
    "人員配置の相談",
    "外部委託先の評価",
]
FAQ_PAIRS = [
    ("社員証を紛失した", "総務部（内線3300）へ即日連絡。再発行は申請から5営業日。"),
    ("名刺を発注したい", "名刺発注フォームから申請。100枚単位、納期は1週間。"),
    ("領収書を紛失した", "支払証明書を作成し、所属長の承認を得て経理部へ提出。"),
    ("PCが起動しない", "電源長押しで強制終了後、再起動。改善しなければ内線4401。"),
    ("メールの容量が上限に達した", "アーカイブを実施。容量追加は情シスへ申請。"),
    ("プリンターの用紙がない", "各フロアの備品棚に予備あり。無い場合は総務部へ。"),
    ("プリンタが紙詰まりした", "前面カバーを開けて用紙を除去。頻発する場合は総務部へ。"),
    ("郵便物を出したい", "1F受付の集荷ボックスへ。15時締切。"),
    ("健康診断の日程を知りたい", "人事部より別途案内。"),
]


def build_noise_docs(rng: random.Random, count: int) -> list[Doc]:
    """ノイズ文書を生成する。

    検索対象を増やして「関係ない文書に埋もれる」状況を作るのが目的。
    中核文書と紛らわしい語を含めることで、検索の取りこぼしを起こしやすくする。
    """
    docs: list[Doc] = []

    # 議事録
    for i in range(count // 3):
        dept = rng.choice(DEPARTMENTS)
        topic = rng.choice(TOPICS)
        month = rng.randint(1, 12)
        docs.append(
            {
                "doc_id": f"MTG-{700 + i}",
                "title": f"{dept} 定例MTG議事録（2025年{month}月）",
                "category": "その他",
                "fmt": "md",
                "body": f"""# {dept} 定例MTG議事録

日付：2025年{month}月{rng.randint(1, 28)}日
出席：{dept} メンバー {rng.randint(4, 12)}名

## 議題
{topic}

## 決定事項
- {topic}について、次回までに各担当が案を持ち寄る
- 関連する規程の確認を{rng.choice(DEPARTMENTS)}へ依頼する

## 保留事項
- 予算措置については経理部と要相談
- スケジュールは次回MTGで確定する

## 次回
2025年{month % 12 + 1}月 第{rng.randint(1, 4)}週
""",
                "dirt": "ノイズ。規程名を断片的に含み、検索で紛れ込みやすい",
            }
        )

    # FAQ
    for i in range(count // 3):
        q, a = FAQ_PAIRS[i % len(FAQ_PAIRS)]
        docs.append(
            {
                "doc_id": f"FAQ-{800 + i}",
                "title": f"よくある質問：{q}",
                "category": "その他",
                "fmt": "md",
                "body": f"""# よくある質問

## Q. {q}

A. {a}

## 関連
不明な点は各担当部署へお問い合わせください。
社内ポータルの「よくある質問」も併せてご確認ください。
""",
                "dirt": "ノイズ。プリンター／プリンタの表記ゆれを含む（実務で頻出する形）",
            }
        )

    # 雑多な手順書
    remaining = count - len(docs)
    for i in range(remaining):
        dept = rng.choice(DEPARTMENTS)
        docs.append(
            {
                "doc_id": f"DOC-{900 + i}",
                "title": f"{dept} 業務手順メモ {i + 1}",
                "category": "その他",
                "fmt": "md",
                "body": f"""# {dept} 業務手順メモ

## 概要
{dept}における日常業務の手順をまとめたもの。
詳細は各規程を参照すること。

## 手順
1. 担当者が起票する
2. 所属長が内容を確認する
3. 承認後、システムに登録する
4. 関係部署へ共有する

## 注意
- 期限を過ぎた申請は受理されない場合がある
- 不明点は{rng.choice(DEPARTMENTS)}へ確認すること
""",
                "dirt": "ノイズ。『期限を過ぎた申請』など中核文書と似た表現を含む",
            }
        )

    return docs


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------


def expand_body(doc: Doc) -> str:
    """本文に形式的な条文を足して、実務の規程並みの長さにする。

    短文コーパスでは1文書＝1チャンクになり、チャンクサイズもオーバーラップも
    効き幅がゼロだった。分割を実際に発生させるために長文版を用意する。

    **元の本文は一切変更しない。** 評価問題の答えはすべて元の本文にあり、
    そこを書き換えると評価が成立しなくなる。

    追加条文は文書ごとに変える（同じ埋め草を全文書に付けると、
    検索が「どの文書も似ている」と判断してしまう）。選び方は doc_id から
    決定的に導き、再生成しても同じ結果になるようにする。
    """
    is_regulation = doc["doc_id"].startswith("REG-")
    preamble = REGULATION_PREAMBLE if is_regulation else PROCEDURE_PREAMBLE
    appendix = REGULATION_APPENDIX if is_regulation else PROCEDURE_APPENDIX

    rng = random.Random(doc["doc_id"])
    extras = rng.sample(EXTRA_SECTIONS, k=5)

    return "\n".join([preamble, doc["body"], *extras, appendix])


def write_md(doc: Doc, out_dir: Path, long_form: bool = False) -> Path:
    """Markdown を出力する。long_form なら形式的な条文を足して長くする。"""
    path = out_dir / f"{doc['doc_id']}_{doc['title']}.md"
    path.write_text(expand_body(doc) if long_form else doc["body"], encoding="utf-8")
    return path


def write_table_pdf(doc: Doc, out_dir: Path) -> Path:
    """表を PDF に描画する。

    **罫線とテキストを別々に描くだけで、構造情報は持たせない。**
    実際の業務PDFもこうなっており、これがパース品質の差を生む。
    """
    path = out_dir / f"{doc['doc_id']}_{doc['title']}.pdf"
    rows = TABLE_DATA[doc["doc_id"]]

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont(JP_FONT, 14)
    c.drawString(50, height - 60, doc["title"])

    c.setFont(JP_FONT, 9)
    col_width = (width - 100) / len(rows[0])
    row_height = 22
    top = height - 100

    for r, row in enumerate(rows):
        y = top - r * row_height
        for col, cell in enumerate(row):
            x = 50 + col * col_width
            c.rect(x, y - row_height, col_width, row_height, stroke=1, fill=0)
            if cell:
                c.drawString(x + 4, y - row_height + 7, cell)

    c.save()
    return path


def write_scan_pdf(doc: Doc, out_dir: Path) -> Path:
    """テキストを画像として描画し、PDF に埋め込む。

    **テキストレイヤーを持たないので、通常の抽出では読めない。**
    スキャンした紙文書を再現している。実務では必ず混ざる。
    """
    path = out_dir / f"{doc['doc_id']}_{doc['title']}.pdf"

    img_width, img_height = 1240, 1754  # A4 相当（150dpi）
    image = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(SCAN_FONT_PATH, 28)

    y = 120
    for line in doc["body"].split("\n"):
        draw.text((100, y), line, fill=(30, 30, 30), font=font)
        y += 46

    # スキャンらしさを出すため、わずかに回転させる。
    # OCR の難易度が現実に近づく。
    image = image.rotate(0.4, fillcolor="white", expand=False)

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, width=A4[0], height=A4[1])
    c.save()
    return path


def main() -> None:
    """題材文書一式を生成する。--long で長文版を out_long/ に出力する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--long", action="store_true",
                        help="形式的な条文を足した長文版を out_long/ に生成する")
    args = parser.parse_args()
    out_dir = LONG_OUT_DIR if args.long else OUT_DIR
    # 日本語 CID フォントを登録する。これを忘れると setFont で KeyError になる。
    pdfmetrics.registerFont(UnicodeCIDFont(JP_FONT))

    rng = random.Random(SEED)
    out_dir.mkdir(exist_ok=True)

    for old in out_dir.glob("*"):
        old.unlink()

    noise = build_noise_docs(rng, count=39)
    all_docs = CORE_DOCS + TABLE_DOCS + SCAN_DOCS + noise

    counts = {"md": 0, "table_pdf": 0, "scan_pdf": 0}
    for doc in all_docs:
        if doc["fmt"] == "md":
            write_md(doc, out_dir, long_form=args.long)
        elif doc["fmt"] == "table_pdf":
            # 表と画像は長文化しない。構造そのものが測定対象なので変えない。
            write_table_pdf(doc, out_dir)
        elif doc["fmt"] == "scan_pdf":
            write_scan_pdf(doc, out_dir)
        counts[doc["fmt"]] += 1

    print(f"生成完了: 合計 {len(all_docs)} 件 → {out_dir}")
    print(f"  Markdown  : {counts['md']} 件")
    print(f"  表PDF     : {counts['table_pdf']} 件（パース品質の差が出る）")
    print(f"  画像PDF   : {counts['scan_pdf']} 件（テキスト抽出不可）")
    print(f"  うち中核  : {len(CORE_DOCS) + len(TABLE_DOCS) + len(SCAN_DOCS)} 件（評価問題の根拠）")


if __name__ == "__main__":
    main()

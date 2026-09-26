"""PDF の結合と、命名規則に沿ったリネーム。"""

import re
import unicodedata
from datetime import date
from pathlib import Path

from pypdf import PdfWriter

# 支店の判定。ファイル名の表記がバラバラなので、支店IDと想定される綴りを対応づける。
BRANCH_PATTERNS: dict[str, tuple[str, ...]] = {
    "TKY": ("tokyo", "東京", "tky"),
    "OSK": ("osaka", "大阪", "osk"),
    "NGO": ("nagoya", "名古屋", "ngo"),
    "FUK": ("fukuoka", "福岡", "fuk"),
    "SPR": ("sapporo", "札幌", "spr"),
}


def detect_branch(filename: str) -> str | None:
    """ファイル名から支店IDを判定する。判定できなければ None（呼び出し側が記録する）。"""
    normalized = unicodedata.normalize("NFKC", filename).lower()
    for branch_id, patterns in BRANCH_PATTERNS.items():
        if any(p.lower() in normalized for p in patterns):
            return branch_id
    return None


def rename_pdfs(input_dir: Path, output_dir: Path, target_month: date) -> tuple[list[tuple[str, str]], list[str]]:
    """命名規則 `{支店ID}_{YYYYMM}_報告書.pdf` に沿ってコピーする。

    元ファイルは残す（リネームではなくコピー）。**元に戻せない操作をバッチでしない。**
    判定できなかったファイルは処理せず、名前を返す。

    @returns (変換したファイルの一覧, 判定できなかったファイルの一覧)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    renamed: list[tuple[str, str]] = []
    unknown: list[str] = []

    for path in sorted(input_dir.glob("*.pdf")):
        branch_id = detect_branch(path.name)
        if branch_id is None:
            unknown.append(path.name)
            continue
        new_name = f"{branch_id}_{target_month.strftime('%Y%m')}_報告書.pdf"
        (output_dir / new_name).write_bytes(path.read_bytes())
        renamed.append((path.name, new_name))

    return renamed, unknown


def merge_pdfs(pdf_dir: Path, output_path: Path) -> list[str]:
    """PDF を支店ID順に結合する。

    @returns 結合した順のファイル名
    """
    paths = sorted(pdf_dir.glob("*.pdf"))
    if not paths:
        raise ValueError(f"結合する PDF がありません: {pdf_dir}")

    writer = PdfWriter()
    for path in paths:
        writer.append(str(path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        writer.write(f)
    return [p.name for p in paths]

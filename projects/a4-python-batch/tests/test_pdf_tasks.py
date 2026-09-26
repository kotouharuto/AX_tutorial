"""PDF のリネーム・結合のテスト。"""

import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from pdf_tasks import detect_branch, merge_pdfs, rename_pdfs  # noqa: E402

INPUT_PDF = BASE_DIR / "input" / "pdf"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report_tokyo_202608.pdf", "TKY"),
        ("大阪支店 月次報告(8月).pdf", "OSK"),   # 日本語・スペース・括弧
        ("NGO-2026_08_report.pdf", "NGO"),
        ("fuk202608.pdf", "FUK"),
        ("札幌_報告書_最終版.pdf", "SPR"),
        ("謎のファイル.pdf", None),              # 判定できないものは None
    ],
)
def test_detect_branch(filename: str, expected: str | None) -> None:
    assert detect_branch(filename) == expected


def test_rename_pdfs(tmp_path: Path) -> None:
    """5本すべて判定でき、命名規則に沿うこと。元ファイルが残ること。"""
    renamed, unknown = rename_pdfs(INPUT_PDF, tmp_path, date(2026, 8, 1))
    assert len(renamed) == 5
    assert unknown == []
    assert {after for _, after in renamed} == {
        f"{b}_202608_報告書.pdf" for b in ("TKY", "OSK", "NGO", "FUK", "SPR")
    }
    assert len(list(INPUT_PDF.glob("*.pdf"))) == 5, "元ファイルが消えている"


def test_merge_pdfs(tmp_path: Path) -> None:
    """結合できること。"""
    from pypdf import PdfReader

    rename_pdfs(INPUT_PDF, tmp_path / "renamed", date(2026, 8, 1))
    out = tmp_path / "merged.pdf"
    merged = merge_pdfs(tmp_path / "renamed", out)
    assert len(merged) == 5
    assert len(PdfReader(out).pages) == 5


def test_merge_pdfs_raises_when_empty(tmp_path: Path) -> None:
    """対象が0件のとき、空のPDFを作らず例外にすること。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="結合する PDF がありません"):
        merge_pdfs(empty, tmp_path / "out.pdf")

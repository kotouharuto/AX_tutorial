"""読み込みと正規化のテスト。

期待値は 2026-09-26 にユーザーが Excel 上で確認済み（東京支店の合計 = 176）。
生成スクリプトのシードが固定されているため、再生成しても同じ値になる。

Windows でも通ることを確認するため、CI（windows-latest）でも実行する。
cp932 の扱いとパス区切りは OS で挙動が変わりうる箇所。
"""

import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from loader import (  # noqa: E402
    detect_encoding,
    find_header_row,
    load_all,
    normalize_text,
    parse_count,
    parse_date,
)

INPUT_EXCEL = BASE_DIR / "input" / "excel"

# ユーザー確認済みの期待値（2026-09-26）
EXPECTED_BRANCH_TOTALS = {"名古屋": 164, "大阪": 179, "札幌": 175, "東京": 176, "福岡": 212}
EXPECTED_GRAND_TOTAL = 906
EXPECTED_DETAIL_ROWS = 80


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ｼｽﾃﾑ障害", "システム障害"),   # 半角カナ → 全角
        ("１４", "14"),                  # 全角数字 → 半角
        ("大 阪", "大阪"),               # 全角スペース除去
        ("  東京  ", "東京"),            # 前後の空白
        ("備品・設備", "備品・設備"),      # 変わらないこと
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/08/05", date(2026, 8, 5)),
        ("2026-08-05", date(2026, 8, 5)),
        (date(2026, 8, 5), date(2026, 8, 5)),
        ("2026年8月5日", date(2026, 8, 5)),
        ("不明", None),      # 変換できないものは None（呼び出し側が記録する）
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: date | None) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(14, 14), ("14", 14), ("１４", 14), (14.0, 14), ("abc", None), (None, None)],
)
def test_parse_count(raw: object, expected: int | None) -> None:
    assert parse_count(raw) == expected


def test_detect_encoding_cp932() -> None:
    """cp932 の CSV を判定できること。Windows でも同じ判定になるかを確認する。"""
    assert detect_encoding(INPUT_EXCEL / "SPR_2026-08.csv") == "cp932"


def test_find_header_row_raises_when_missing() -> None:
    """ヘッダが見つからないときは黙って進まず例外にすること。"""
    with pytest.raises(ValueError, match="ヘッダ行が見つかりません"):
        find_header_row([["タイトル"], [None], ["列A", "列B"]])


def test_load_all_row_count() -> None:
    """明細行数が期待どおりであること（空行・合計行を除いた数）。"""
    df, _ = load_all(INPUT_EXCEL)
    assert len(df) == EXPECTED_DETAIL_ROWS


def test_load_all_removes_dirt() -> None:
    """表記ゆれが吸収され、支店・種別が既定の集合に収まること。"""
    df, _ = load_all(INPUT_EXCEL)
    assert set(df["支店"]) == set(EXPECTED_BRANCH_TOTALS)
    assert set(df["種別"]) == {"システム障害", "申請手続き", "備品・設備", "その他"}
    assert df["日付"].map(type).eq(date).all(), "日付が date に統一されていない"


def test_branch_totals_match_verified_values() -> None:
    """支店別の合計が、ユーザー確認済みの値と一致すること。"""
    df, _ = load_all(INPUT_EXCEL)
    actual = df.groupby("支店")["件数"].sum().to_dict()
    assert actual == EXPECTED_BRANCH_TOTALS
    assert sum(actual.values()) == EXPECTED_GRAND_TOTAL


def test_report_records_what_was_dropped() -> None:
    """除去した行数が記録されていること。黙って捨てていないことの確認。"""
    _, reports = load_all(INPUT_EXCEL)
    assert all(r.dropped_empty >= 1 for r in reports), "空行の除去が記録されていない"
    xlsx_reports = [r for r in reports if r.source.endswith(".xlsx")]
    assert all(r.dropped_summary == 1 for r in xlsx_reports), "合計行の除去が記録されていない"
    assert not any(r.invalid_dates or r.invalid_counts for r in reports), "変換失敗があってはならない"

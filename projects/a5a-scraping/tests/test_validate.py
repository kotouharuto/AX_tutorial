"""異常判定のテスト。

**break_selector.py で実際に観察した3つの壊れ方を再現し、
すべて異常として検出できることを確かめる。** これがこのモジュールの存在理由。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from validate import (  # noqa: E402
    DEFAULT_MAX_EMPTY_RATE,
    ValidationReport,
    empty_rate,
    format_report,
    load_state,
    save_state,
    validate,
)

FIELDS = ("title", "price")


def make_items(count: int, title: str = "書名", price: str = "£51.77") -> list[dict]:
    """正常な取得結果を作る。"""
    return [{"title": f"{title}{i}", "price": price} for i in range(count)]


# --- break_selector.py で観察した3ケース --------------------------------------


def test_クラス名が変わったケースを検出する() -> None:
    """セレクタが一致せず0件になった場合。件数で捕まる。"""
    report = validate("books", [], FIELDS, previous_count=1000)
    assert not report.ok
    assert any("0件" in p for p in report.problems)


def test_階層が1段増えたケースを検出する() -> None:
    """件数は正常だが書名が全件空。**件数では捕まらない壊れ方。**"""
    items = [{"title": "", "price": "£51.77"} for _ in range(20)]
    report = validate("books", items, FIELDS, previous_count=20)
    assert report.count == 20, "件数は正常であること（これが厄介な点）"
    assert not report.ok
    assert any("title" in p for p in report.problems)


def test_価格だけ変わったケースを検出する() -> None:
    """件数も書名も正常で、価格だけが全件空。**差分検出でも捕まらない壊れ方。**"""
    items = [{"title": f"書名{i}", "price": ""} for i in range(20)]
    report = validate("books", items, FIELDS, previous_count=20)
    assert not report.ok
    assert any("price" in p for p in report.problems)
    assert all("title" not in p for p in report.problems), "title は正常なので挙げない"


# --- 件数の判定 ---------------------------------------------------------------


def test_正常な結果は異常なしになる() -> None:
    report = validate("books", make_items(1000), FIELDS, previous_count=1000)
    assert report.ok
    assert report.problems == []


def test_急減を検出する() -> None:
    report = validate("books", make_items(400), FIELDS, previous_count=1000)
    assert not report.ok
    assert any("急減" in p for p in report.problems)


def test_閾値ちょうどの減少は異常としない() -> None:
    """前回比 50%（既定の閾値）は「下回っていない」ので通す。境界の挙動を固定する。"""
    report = validate("books", make_items(500), FIELDS, previous_count=1000)
    assert report.ok


def test_増加は異常としない() -> None:
    report = validate("books", make_items(1200), FIELDS, previous_count=1000)
    assert report.ok


def test_前回の記録がない初回は急減判定をしない() -> None:
    report = validate("books", make_items(1000), FIELDS, previous_count=None)
    assert report.ok
    assert "判定できない" in format_report(report), "判定できなかったことを明示する"


def test_前回が0件なら急減判定をしない() -> None:
    """0 で割らない。前回が異常値だった場合に比率を出しても意味がない。"""
    report = validate("books", make_items(10), FIELDS, previous_count=0)
    assert report.ok


# --- 空率の計算 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([], 0.0),
        ([{"title": "a"}], 0.0),
        ([{"title": ""}], 1.0),
        ([{"title": None}], 1.0),
        ([{}], 1.0),
        ([{"title": "a"}, {"title": ""}], 0.5),
        ([{"title": []}], 1.0),
    ],
)
def test_空率を計算する(items: list[dict], expected: float) -> None:
    assert empty_rate(items, "title") == pytest.approx(expected)


def test_数値のゼロは空とみなさない() -> None:
    """0 や False を空扱いすると、正常な値を異常と判定してしまう。"""
    assert empty_rate([{"count": 0}], "count") == 0.0
    assert empty_rate([{"flag": False}], "flag") == 0.0


def test_空率が閾値以下なら通す() -> None:
    """1件だけ欠けるサイト側の事情は許容する（閾値 5%）。"""
    items = make_items(100)
    items[0]["title"] = ""
    report = validate("books", items, FIELDS, previous_count=100)
    assert report.empty_rates["title"] == pytest.approx(0.01)
    assert report.ok


def test_空率が閾値を超えたら異常() -> None:
    items = make_items(100)
    for i in range(10):
        items[i]["title"] = ""
    report = validate("books", items, FIELDS, previous_count=100)
    assert not report.ok


def test_閾値は上書きできる() -> None:
    items = make_items(100)
    items[0]["title"] = ""
    report = validate("books", items, FIELDS, previous_count=100, max_empty_rate=0.0)
    assert not report.ok


def test_0件のときは空率を異常としない() -> None:
    """0件は別の理由で異常。空率でも二重に挙げると原因が分かりにくくなる。"""
    report = validate("books", [], FIELDS, previous_count=10)
    assert sum(1 for p in report.problems if "空の割合" in p) == 0


# --- 状態の保存 ---------------------------------------------------------------


def test_状態を保存して読み戻せる(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state({"books": 1000}, path)
    assert load_state(path) == {"books": 1000}


def test_状態ファイルがなければ空を返す(tmp_path: Path) -> None:
    assert load_state(tmp_path / "none.json") == {}


def test_壊れた状態ファイルは例外にする(tmp_path: Path) -> None:
    """推測で進めない。前回値を読めないなら、そう分かる形で止める。"""
    path = tmp_path / "state.json"
    path.write_text("これは JSON ではない", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_state(path)


# --- 表示 ---------------------------------------------------------------------


def test_異常なしでも判定内容を表示する() -> None:
    """「異常なし」だけでは何を見たか分からない。空率と前回比を必ず出す。"""
    text = format_report(validate("books", make_items(10), FIELDS, previous_count=10))
    assert "異常なし" in text
    assert "title が空" in text
    assert "前回比" in text


def test_異常時は理由を列挙する() -> None:
    text = format_report(validate("books", [], FIELDS, previous_count=1000))
    assert "**異常**" in text
    assert "0件" in text


def test_既定の空率閾値が緩すぎないこと() -> None:
    """閾値が 1.0 などになっていたら、この判定は無意味になる。"""
    assert 0.0 <= DEFAULT_MAX_EMPTY_RATE <= 0.2


def test_report_のok判定() -> None:
    assert ValidationReport(dataset="x", count=1).ok
    assert not ValidationReport(dataset="x", count=1, problems=["何か"]).ok


# --- フィールド名の指定ミス ----------------------------------------------------


def test_存在しないフィールドは指定ミスとして報告する() -> None:
    """セレクタ破壊（空になった）と指定ミス（キーが無い）は対処が違う。区別する。"""
    items = [{"title": "書名", "detail": "£51.77"} for _ in range(10)]
    report = validate("books", items, ("title", "price"))
    assert not report.ok
    problem = next(p for p in report.problems if "price" in p)
    assert "存在しない" in problem
    assert "detail" in problem, "実際に使えるキーを示して次の操作を助ける"


def test_一部にだけ存在するフィールドは空率として報告する() -> None:
    """キー自体はあるので指定ミスではない。セレクタ破壊の疑い。"""
    items = [{"title": "a", "price": ""} for _ in range(9)] + [{"title": "a", "price": "£1"}]
    report = validate("books", items, ("title", "price"))
    assert not report.ok
    assert any("空の割合" in p for p in report.problems)


# --- CLI ----------------------------------------------------------------------


def run_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, items: list[dict],
            fields: str, update: bool = False, state: dict | None = None) -> tuple[int, str]:
    """main() を実処理そのままで走らせる。**状態ファイルは tmp に逃がす。**"""
    import validate as mod

    data_path = tmp_path / "books.json"
    data_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    state_path = tmp_path / "state.json"
    if state is not None:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(mod, "STATE_PATH", state_path)

    argv = ["validate.py", str(data_path), "--fields", fields]
    if update:
        argv.append("--update-state")
    monkeypatch.setattr(sys, "argv", argv)
    code = mod.main()
    return code, state_path.read_text(encoding="utf-8") if state_path.exists() else ""


def test_CLI_は正常なら0を返す(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, _ = run_cli(monkeypatch, tmp_path, make_items(10), "title,price")
    assert code == 0


def test_CLI_は異常なら1を返す(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, _ = run_cli(monkeypatch, tmp_path, [], "title,price")
    assert code == 1


def test_CLI_は正常時に件数を記録する(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, state = run_cli(monkeypatch, tmp_path, make_items(10), "title,price", update=True)
    assert code == 0
    assert json.loads(state) == {"books": 10}


def test_CLI_は異常時に件数を記録しない(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """異常値を次回の基準にすると、以降ずっと見逃す。"""
    code, state = run_cli(
        monkeypatch, tmp_path, [], "title,price", update=True, state={"books": 1000}
    )
    assert code == 1
    assert json.loads(state) == {"books": 1000}, "前回値が上書きされないこと"


def test_CLI_は前回値を読んで急減を判定する(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, _ = run_cli(
        monkeypatch, tmp_path, make_items(10), "title,price", state={"books": 1000}
    )
    assert code == 1

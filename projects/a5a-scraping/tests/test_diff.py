"""差分検出のテスト。

**差分は壊れを検知しない**という前提を明示的に固定する。
セレクタ破壊時に「差分なし」になることをテストで残しておく。
そうしないと、後から見た人が差分検出を健全性の判定に使ってしまう。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diff import (  # noqa: E402
    DiffResult,
    compute_diff,
    format_diff,
    load_snapshot,
    save_snapshot,
)
import diff as diff_mod  # noqa: E402

KEY = "title"


def items(*titles: str, price: str = "£1") -> list[dict]:
    return [{"title": t, "price": price} for t in titles]


# --- 基本 ---------------------------------------------------------------------


def test_初回は差分なしとして扱う() -> None:
    result = compute_diff("books", items("a", "b"), None, KEY)
    assert result.is_first_run
    assert not result.has_changes
    assert "初回" in format_diff(result)


def test_変化がなければ差分なし() -> None:
    result = compute_diff("books", items("a", "b"), items("a", "b"), KEY)
    assert not result.has_changes


def test_追加を検出する() -> None:
    result = compute_diff("books", items("a", "b"), items("a"), KEY)
    assert [i["title"] for i in result.added] == ["b"]
    assert result.removed == []


def test_削除を検出する() -> None:
    result = compute_diff("books", items("a"), items("a", "b"), KEY)
    assert [i["title"] for i in result.removed] == ["b"]
    assert result.added == []


def test_値の変更を検出する() -> None:
    result = compute_diff("books", items("a", price="£2"), items("a", price="£1"), KEY)
    assert len(result.changed) == 1
    before, after = result.changed[0]
    assert before["price"] == "£1"
    assert after["price"] == "£2"
    assert result.added == [] and result.removed == []


# --- 壊れたときの振る舞い（**意図を固定する**）----------------------------------


def test_セレクタ破壊で価格が空になっても差分としては変更扱い() -> None:
    """価格が全件空になったケース。差分では『変更』として出るが、
    **これを異常と判定するのは validate.py の責任**。"""
    previous = items("a", "b", price="£1")
    current = items("a", "b", price="")
    result = compute_diff("books", current, previous, KEY)
    assert len(result.changed) == 2
    assert result.added == [] and result.removed == []


def test_キーが壊れると全件削除と全件追加に見える() -> None:
    """キーに使うフィールドが壊れた場合。差分が爆発するので、
    **キーは最も壊れにくいフィールドを選ぶ**必要がある。"""
    previous = items("a", "b")
    current = [{"title": "", "price": "£1"} for _ in range(2)]
    result = compute_diff("books", current, previous, KEY)
    assert len(result.removed) == 2
    assert result.added == [], "キーが空の項目は差分対象から外れる"


def test_キーが空の項目は警告して差分対象から外す(capsys: pytest.CaptureFixture) -> None:
    compute_diff("books", [{"title": "", "price": "£1"}], items("a"), KEY)
    assert "空の項目" in capsys.readouterr().out


def test_キーの重複を警告する(capsys: pytest.CaptureFixture) -> None:
    compute_diff("books", items("a", "a"), items("a"), KEY)
    assert "重複" in capsys.readouterr().out


# --- スナップショット ----------------------------------------------------------


def test_スナップショットを保存して読み戻せる(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(diff_mod, "SNAPSHOT_DIR", tmp_path)
    save_snapshot("books", items("a"))
    assert load_snapshot("books") == items("a")


def test_スナップショットが無ければNoneを返す(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(diff_mod, "SNAPSHOT_DIR", tmp_path)
    assert load_snapshot("none") is None


def test_空のスナップショットとNoneを区別する(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """0件だったのか、前回が無いのかで扱いが変わる。"""
    monkeypatch.setattr(diff_mod, "SNAPSHOT_DIR", tmp_path)
    save_snapshot("empty", [])
    assert load_snapshot("empty") == []
    assert compute_diff("empty", items("a"), [], KEY).is_first_run is False


def test_壊れたスナップショットは例外にする(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """推測で『前回は無かった』と扱うと、全件が追加として通知される。"""
    monkeypatch.setattr(diff_mod, "SNAPSHOT_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("JSON ではない", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_snapshot("broken")


# --- 表示 ---------------------------------------------------------------------


def test_件数が多いときは省略する() -> None:
    result = compute_diff("books", items(*[str(i) for i in range(100)]), items("x"), KEY)
    text = format_diff(result, max_lines=5)
    assert "ほか" in text
    assert text.count("[追加]") == 6, "5件＋省略行"


def test_変更は変わったフィールドだけを出す() -> None:
    result = compute_diff("books", items("a", price="£2"), items("a", price="£1"), KEY)
    text = format_diff(result)
    assert "price" in text
    assert "title" not in text.split("[変更]")[1], "変わっていないフィールドは出さない"


def test_DiffResult_の判定() -> None:
    assert not DiffResult(dataset="x").has_changes
    assert DiffResult(dataset="x", added=[{}]).has_changes
    assert DiffResult(dataset="x").is_first_run
    assert not DiffResult(dataset="x", previous_count=0).is_first_run

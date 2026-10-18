"""接続の監視のテスト。時刻と接続状態を差し替えて、切れ続けたときの判断を確かめる。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app as app_mod  # noqa: E402
from watchdog import ConnectionWatchdog, clear_marker, read_marker, write_marker  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make(states: list[bool]) -> tuple[ConnectionWatchdog, Clock]:
    clock = Clock()
    it = iter(states)
    return ConnectionWatchdog(lambda: next(it), threshold_sec=300, now=clock), clock


def test_つながっていれば何もしない() -> None:
    wd, clock = make([True] * 3)
    for _ in range(3):
        clock.t += 1000
        assert wd.check() is None


def test_一時的な切断は許す() -> None:
    wd, clock = make([False, True, False])
    clock.t = 200
    assert wd.check() is None  # 200 秒切れているが閾値未満
    clock.t = 250
    assert wd.check() is None  # つながった → 数え直し
    clock.t = 500
    assert wd.check() is None  # 250 秒しか経っていない


def test_切れ続けたら秒数を返す() -> None:
    wd, clock = make([False, False])
    clock.t = 100
    assert wd.check() is None
    clock.t = 301
    assert wd.check() == pytest.approx(301)


def test_つながった直後に切れる状態も切れているとみなす() -> None:
    """今回の壊れ方（つながった直後に切れるのを繰り返す）。
    30 秒ごとに見ると、ほぼ毎回「切れている」と観測される。"""
    wd, clock = make([False] * 11)
    for _ in range(11):
        clock.t += 30
        result = wd.check()
    assert result == pytest.approx(330)


# --- 前回の終了の記録 -----------------------------------------------------------


def test_記録を残して読み戻せる(tmp_path: Path) -> None:
    path = tmp_path / "marker.json"
    write_marker(301.4, path)
    record = read_marker(path)
    assert record is not None and record.down_sec == 301
    clear_marker(path)
    assert read_marker(path) is None


def test_壊れた記録でも起動は止めない(tmp_path: Path) -> None:
    path = tmp_path / "marker.json"
    path.write_text("壊れている", encoding="utf-8")
    record = read_marker(path)
    assert record is not None and record.down_sec == -1


# --- 運用者への通知（起動時） -------------------------------------------------------


class FakeClient:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    def chat_postMessage(self, **kwargs: object) -> None:  # noqa: N802
        if self.fail:
            raise self.fail
        self.sent.append(kwargs)


def test_ネットワークが切れていても例外を出さずFalseを返す() -> None:
    """切れているときに呼ぶこともある。終了処理を止めない。"""
    assert app_mod.post_to_ops(FakeClient(fail=OSError("network down")), "C0OPS00001", "x") is False


@pytest.fixture
def marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """記録の置き場所を一時ディレクトリに向ける。本物の output/ には触れない。"""
    import watchdog

    path = tmp_path / "marker.json"
    monkeypatch.setattr(watchdog, "MARKER_PATH", path)
    return path


def test_前回の終了を知らせたら記録を消す(marker: Path) -> None:
    write_marker(300)
    assert marker.exists(), "差し替えた場所に書かれている（既定値が呼び出し時に決まる）"
    client = FakeClient()
    app_mod.announce_previous_exit(client, "C0OPS00001")
    assert "起動し直しました" in client.sent[0]["text"]
    assert "300 秒" in client.sent[0]["text"]
    assert not marker.exists()


def test_知らせられなければ記録を残し次回また試す(marker: Path) -> None:
    write_marker(300)
    app_mod.announce_previous_exit(FakeClient(fail=OSError("down")), "C0OPS00001")
    assert marker.exists()


def test_前回の記録が無ければ何も送らない(marker: Path) -> None:
    client = FakeClient()
    app_mod.announce_previous_exit(client, "C0OPS00001")
    assert client.sent == []


@pytest.mark.parametrize(("raw", "expected"), [("", 300.0), ("60", 60.0)])
def test_監視の秒数を読む(raw: str, expected: float, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A5B_WATCHDOG_SEC", raw)
    assert app_mod.env_seconds("A5B_WATCHDOG_SEC", 300.0) == expected

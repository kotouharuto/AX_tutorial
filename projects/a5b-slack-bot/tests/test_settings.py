"""設定の検査のテスト。**値を表示しないこと**も確かめる。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import settings as settings_mod  # noqa: E402
from settings import Settings, find_problems, load_env_file  # noqa: E402

GOOD = {
    "SLACK_BOT_TOKEN": "xoxb-1111-2222-abcdef",
    "SLACK_APP_TOKEN": "xapp-1-AAAA-3333-abcdef",
    "GEMINI_API_KEY": "gemini-key-0123456789",
}


def test_正しい設定は問題なし() -> None:
    assert find_problems(GOOD) == []


def test_トークンの取り違えを見つける() -> None:
    swapped = dict(GOOD, SLACK_BOT_TOKEN=GOOD["SLACK_APP_TOKEN"])
    assert any("SLACK_BOT_TOKEN の先頭" in p for p in find_problems(swapped))


def test_全角スペースの混入を見つける() -> None:
    """A-6a で踏んだ。見た目で区別できない。"""
    broken = dict(GOOD, GEMINI_API_KEY="gemini-key\u3000")
    assert any("空白" in p for p in find_problems(broken))


def test_キー名の打ち間違いを見つける() -> None:
    """A-6a で踏んだ（SHEETS）。エラーにならず未設定扱いになる種類。"""
    values = {k: v for k, v in GOOD.items() if k != "GEMINI_API_KEY"}
    values["GEMINI_APIKEY"] = "x"
    problems = find_problems(values)
    assert any("GEMINI_API_KEY が空" in p for p in problems)
    assert any("想定外のキー GEMINI_APIKEY" in p for p in problems)


def test_問題の文言に値を含めない() -> None:
    swapped = dict(GOOD, SLACK_BOT_TOKEN=GOOD["SLACK_APP_TOKEN"])
    text = "".join(find_problems(swapped))
    assert all(v not in text for v in GOOD.values())


def test_envファイルを読む(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('# コメント\n\nSLACK_BOT_TOKEN="xoxb-x"\n壊れた行\n', encoding="utf-8")
    assert load_env_file(path) == {"SLACK_BOT_TOKEN": "xoxb-x"}


def test_reprにトークンが出ない() -> None:
    s = Settings(GOOD["SLACK_BOT_TOKEN"], GOOD["SLACK_APP_TOKEN"], GOOD["GEMINI_API_KEY"])
    assert all(v not in repr(s) for v in GOOD.values())


def test_検査の画面出力に値が出ない(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{k}={v}" for k, v in GOOD.items()), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "ENV_PATH", path)
    monkeypatch.setattr(settings_mod, "load_env_file", lambda p=path: load_env_file(p))
    assert settings_mod.main() == 0
    out = capsys.readouterr().out
    assert "問題なし" in out
    assert all(v not in out for v in GOOD.values())

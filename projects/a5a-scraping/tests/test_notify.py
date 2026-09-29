"""通知のテスト。**ネットワークには一切出ない。**

重点は2つ。
1. 既定で送信しないこと（設定ミスで意図せず送るより安全）
2. パスワードが表示・ログ・例外メッセージに出ないこと
"""

import smtplib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import notify as notify_mod  # noqa: E402
from notify import (  # noqa: E402
    MailConfig,
    NotifyConfigError,
    build_message,
    load_config,
    load_env,
    redact,
    send,
)

SECRET = "abcd efgh ijkl mnop"

FULL_ENV = {
    "NOTIFY_ENABLED": "true",
    "NOTIFY_FROM": "from@example.com",
    "NOTIFY_TO": "to@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "from@example.com",
    "SMTP_PASSWORD": SECRET,
}


# --- .env の読み込み ------------------------------------------------------------


def test_env_を読む(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# コメント",
                "",
                "NOTIFY_ENABLED=true",
                'SMTP_PASSWORD="abc def"',
                "SMTP_USER = spaced@example.com ",
                "壊れた行",
            ]
        ),
        encoding="utf-8",
    )
    env = load_env(path)
    assert env["NOTIFY_ENABLED"] == "true"
    assert env["SMTP_PASSWORD"] == "abc def", "引用符を外す"
    assert env["SMTP_USER"] == "spaced@example.com", "前後の空白を落とす"
    assert "壊れた行" not in env


def test_env_が無ければ空(tmp_path: Path) -> None:
    assert load_env(tmp_path / "none") == {}


# --- 既定で送信しない ----------------------------------------------------------


def test_既定は無効() -> None:
    assert not load_config({}).enabled


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "", "adsf"])
def test_無効と解釈される値(value: str) -> None:
    assert not load_config({"NOTIFY_ENABLED": value}).enabled


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", " TRUE "])
def test_有効と解釈される値(value: str) -> None:
    env = dict(FULL_ENV, NOTIFY_ENABLED=value)
    assert load_config(env).enabled


def test_無効なら送信せず本文を出す(capsys: pytest.CaptureFixture) -> None:
    config = load_config({})
    assert send(config, "件名", "本文") is False
    out = capsys.readouterr().out
    assert "未送信" in out
    assert "本文" in out


def test_有効なのに設定不足なら例外() -> None:
    """**送ったつもりで送れていない**状態を作らない。"""
    with pytest.raises(NotifyConfigError) as exc:
        load_config({"NOTIFY_ENABLED": "true"})
    for name in ("NOTIFY_FROM", "NOTIFY_TO", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        assert name in str(exc.value)


def test_ポートが数値でなければ例外() -> None:
    with pytest.raises(NotifyConfigError):
        load_config(dict(FULL_ENV, SMTP_PORT="いち"))


# --- パスワードを出さない ------------------------------------------------------


def test_reprにパスワードが出ない() -> None:
    config = load_config(FULL_ENV)
    text = repr(config)
    assert SECRET not in text
    assert "***" in text


def test_redactがパスワードを消す() -> None:
    config = load_config(FULL_ENV)
    assert SECRET not in redact(f"エラー: {SECRET} が不正", config)


def test_パスワードが空ならredactは何もしない() -> None:
    config = MailConfig(False, "", "", "", 587, "", "")
    assert redact("そのまま", config) == "そのまま"


def test_認証失敗時のメッセージにパスワードが出ない(monkeypatch: pytest.MonkeyPatch) -> None:
    """例外文をそのまま流すと、サーバ応答に認証情報が混ざる可能性がある。"""

    class FakeSMTP:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def starttls(self, **k: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(
                535, f"5.7.8 Username and Password not accepted {password}".encode()
            )

    monkeypatch.setattr(notify_mod.smtplib, "SMTP", FakeSMTP)
    config = load_config(FULL_ENV)
    with pytest.raises(NotifyConfigError) as exc:
        send(config, "件名", "本文")
    assert SECRET not in str(exc.value)
    assert "アプリパスワード" in str(exc.value), "原因と対処を示す"


def test_送信失敗時のメッセージにパスワードが出ない(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingSMTP:
        def __init__(self, *a: object, **k: object) -> None:
            raise OSError(f"接続失敗 {SECRET}")

    monkeypatch.setattr(notify_mod.smtplib, "SMTP", FailingSMTP)
    with pytest.raises(NotifyConfigError) as exc:
        send(load_config(FULL_ENV), "件名", "本文")
    assert SECRET not in str(exc.value)


# --- 送信 ---------------------------------------------------------------------


def test_有効なら送信する(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 0) -> None:
            sent.append(("connect", host, port))

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def starttls(self, **k: object) -> None:
            sent.append(("starttls",))

        def login(self, user: str, password: str) -> None:
            sent.append(("login", user))

        def send_message(self, message: object) -> None:
            sent.append(("send", message))

    monkeypatch.setattr(notify_mod.smtplib, "SMTP", FakeSMTP)
    assert send(load_config(FULL_ENV), "件名", "本文") is True
    kinds = [s[0] for s in sent]
    assert kinds == ["connect", "starttls", "login", "send"], "STARTTLS を login より先に行う"


def test_日本語の件名と本文がUTF8で組まれる() -> None:
    config = load_config(FULL_ENV)
    message = build_message(config, "【異常】取得0件", "本文に日本語を含む")
    assert message["To"] == "to@example.com"
    assert "utf-8" in str(message.get_content_type()) or message.get_content_charset() == "utf-8"
    assert "本文に日本語を含む" in message.get_content()

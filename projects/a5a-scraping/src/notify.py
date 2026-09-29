"""異常と差分をメールで通知する。

【既定で送信しない】`NOTIFY_ENABLED=false` の間は本文を標準出力に出すだけ。
設定ミスで意図せず送信されるより、送られない方が損失が小さい。
実際に送るときだけ明示的に有効化する。

【秘密情報】SMTP のパスワードは `.env` から読む。
コードにもコミットにも含めない（`.env` は `.gitignore` で除外済み）。
**ログにも出さない。** 失敗時のメッセージにパスワードが混ざらないよう、
例外メッセージをそのまま流さずに整形する。
"""

import os
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# ログに出してはいけない環境変数名。**部分一致で判定する。**
SECRET_KEYS = ("PASSWORD", "TOKEN", "SECRET", "KEY")


class NotifyConfigError(RuntimeError):
    """通知設定の不足・誤り。**黙って送信をスキップせず、明示的に落とす。**"""


@dataclass(frozen=True)
class MailConfig:
    """通知設定。`__repr__` を持たせないことでパスワードの露出を防ぐ。"""

    enabled: bool
    sender: str
    recipient: str
    host: str
    port: int
    user: str
    password: str

    def __repr__(self) -> str:
        """**パスワードを絶対に出さない。** デバッグ出力に混ざる事故を防ぐ。"""
        return (
            f"MailConfig(enabled={self.enabled}, sender={self.sender!r}, "
            f"recipient={self.recipient!r}, host={self.host!r}, port={self.port}, "
            f"user={self.user!r}, password=***)"
        )


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    """.env を読む。python-dotenv を入れずに済む程度の単純な形式だけ扱う。

    対応：`KEY=VALUE`、`#` 始まりのコメント、空行、値の前後の引用符。
    非対応：複数行の値、変数展開。**必要になったら dotenv を入れる。**
    """
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def load_config(env: dict[str, str] | None = None) -> MailConfig:
    """設定を組み立てる。有効化されている場合のみ必須項目を検査する。

    `env` を渡した場合はそれだけを使う（テスト用）。
    渡さない場合は `.env` を読み、実行環境の環境変数で上書きする
    （launchd や CI から差し替えられるようにするため）。
    """
    if env is not None:
        values = dict(env)
    else:
        values = dict(load_env())
        values.update(
            {k: v for k, v in os.environ.items() if k.startswith(("NOTIFY_", "SMTP_"))}
        )

    enabled = values.get("NOTIFY_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    try:
        port = int(values.get("SMTP_PORT", "587"))
    except ValueError as exc:
        raise NotifyConfigError(f"SMTP_PORT が数値でない: {values.get('SMTP_PORT')!r}") from exc

    config = MailConfig(
        enabled=enabled,
        sender=values.get("NOTIFY_FROM", "").strip(),
        recipient=values.get("NOTIFY_TO", "").strip(),
        host=values.get("SMTP_HOST", "").strip(),
        port=port,
        user=values.get("SMTP_USER", "").strip(),
        password=values.get("SMTP_PASSWORD", ""),
    )

    if config.enabled:
        # 有効なのに設定が欠けている状態は、**送ったつもりで送れていない**最悪の形。
        missing = [
            name
            for name, value in (
                ("NOTIFY_FROM", config.sender),
                ("NOTIFY_TO", config.recipient),
                ("SMTP_HOST", config.host),
                ("SMTP_USER", config.user),
                ("SMTP_PASSWORD", config.password),
            )
            if not value
        ]
        if missing:
            raise NotifyConfigError(
                "NOTIFY_ENABLED=true だが設定が不足している: " + ", ".join(missing)
            )
    return config


def redact(text: str, config: MailConfig) -> str:
    """本文・エラーメッセージからパスワードを除去する。"""
    if config.password:
        text = text.replace(config.password, "***")
    return text


def build_message(config: MailConfig, subject: str, body: str) -> EmailMessage:
    """メールを組み立てる。日本語の件名・本文が化けないよう UTF-8 を明示する。"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = config.recipient
    message.set_content(body, charset="utf-8")
    return message


def send(config: MailConfig, subject: str, body: str) -> bool:
    """送信する。無効なら標準出力に出して False を返す。"""
    if not config.enabled:
        print("--- 通知（未送信・NOTIFY_ENABLED=false）---")
        print(f"件名: {subject}")
        print(body)
        print("--- ここまで ---")
        return False

    message = build_message(config, subject, body)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(config.host, config.port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(config.user, config.password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        # Gmail はアプリパスワード未発行だとここで落ちる。原因を具体的に示す。
        raise NotifyConfigError(
            "SMTP 認証に失敗した。Gmail の場合、通常のパスワードではなく"
            "アプリパスワード（2段階認証が前提）が必要。"
            f" サーバの応答: {redact(str(exc.smtp_error.decode(errors='replace')), config)}"
        ) from None
    except (smtplib.SMTPException, OSError) as exc:
        # 例外文にパスワードが含まれる可能性を考えて必ず通す
        raise NotifyConfigError(f"SMTP 送信に失敗した: {redact(str(exc), config)}") from None
    return True


def main() -> int:
    """設定を確認する。**パスワードは表示しない。**"""
    force_utf8_stdio()

    config = load_config()
    print(repr(config))
    if not config.enabled:
        print("\n通知は無効。有効にするには .env で NOTIFY_ENABLED=true にする。")
        print("Gmail を使う場合、SMTP_PASSWORD にはアプリパスワードを入れる")
        print("（通常のログインパスワードでは認証に失敗する）。")
        return 0

    print("\nテスト送信する。")
    sent = send(config, "[A-5a] テスト送信", "この本文が届けば設定は正しい。")
    print("送信した" if sent else "送信しなかった")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A-5b の Slack Bot。Socket Mode で動く（公開 URL 不要）。

【受信したらすぐ ack する】Slack はスラッシュコマンドに3秒以内の応答を求める。
素朴な実装（分類が終わってから ack）では、Gemini だけで 2.80 秒かかり期限ぎりぎりだった。
観察用に4秒遅らせると、3秒の時点で Bolt が失敗を返し、利用者には
「アプリが応答しなかったため、/inquiry は失敗しました。もう一度試すか…」と出た。
しかも遅れて結果も表示され、言われたとおり再送すると二重に登録される状態だった。
→ 受け付けたことを先に返し、分類はそのあとで行って respond() で結果を送る。

【観察専用の遅延】環境変数 A5B_SIMULATED_DELAY_SEC で分類の前に待たせる（既定は 0）。本番では使わない。

実行：uv run python src/app.py
"""

import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classifier import Classification, ClassificationError, classify  # noqa: E402
from messages import (  # noqa: E402
    ACCEPTED,
    EMPTY_GUIDE,
    failure_message,
    notify_failure_message,
    result_message,
    routed_message,
)
from notifier import NotifyError  # noqa: E402

# ログは標準エラー出力へ。**問い合わせの本文は出さない**（個人情報が入りうる）
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("a5b")


def simulated_delay() -> float:
    """観察専用の遅延（秒）。数値でなければ止める（黙って 0 として扱わない）。"""
    raw = os.environ.get("A5B_SIMULATED_DELAY_SEC", "0").strip() or "0"
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"A5B_SIMULATED_DELAY_SEC が数値ではない：{raw!r}") from None


def handle_inquiry(
    text: str,
    user_id: str,
    ack: Callable[..., object],
    respond: Callable[..., object],
    classify_fn: Callable[[str], Classification],
    notify_fn: Callable[[Classification, str, str], tuple[str, bool]],
    alert_fn: Callable[..., bool],
    delay: float = 0.0,
) -> None:
    """問い合わせを処理する。Slack に依存しない形にして、テストから呼べるようにしている。

    順序が要点：**ack を最初に呼ぶ。** 分類と通知はそのあと。
    """
    started = time.monotonic()
    if not text.strip():
        ack(EMPTY_GUIDE)  # 本文が無いなら分類しない。すぐ案内を返す
        return

    ack(ACCEPTED)
    logger.info("受信：%d 文字。ack を返した（受信から %.2f 秒）", len(text), time.monotonic() - started)

    if delay:
        time.sleep(delay)

    try:
        result = classify_fn(text)
    except ClassificationError as exc:
        logger.warning("分類の失敗：%s", exc)
        alerted = alert_fn("分類の失敗", str(exc), user_id, text)
        if not alerted:
            logger.error("運用者への通知も失敗した（分類の失敗）")
        respond(text=failure_message(str(exc), alerted))
        return

    fallback, blocks = result_message(result)
    try:
        channel, is_fallback = notify_fn(result, text, user_id)
    except NotifyError as exc:
        logger.error("通知の失敗：%s", exc)
        alerted = alert_fn("通知の失敗", str(exc), user_id, text, exc)
        if not alerted:
            logger.error("運用者への通知も失敗した（通知の失敗）")
        # **blocks があると text は画面に出ない。** 失敗の文は必ず blocks に入れる。
        # 当初 text にだけ入れており、利用者には分類結果しか見えず「届いた」と思い込む状態だった
        warning = notify_failure_message(exc.code, alerted)
        respond(
            text=fallback + "\n" + warning,
            blocks=blocks + [{"type": "section", "text": {"type": "mrkdwn", "text": ":warning: " + warning}}],
        )
        return

    respond(
        text=fallback + "\n" + routed_message(channel, is_fallback),
        blocks=blocks + [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": routed_message(channel, is_fallback)}]}
        ],
    )
    logger.info(
        "結果を送った：受信から %.2f 秒（Gemini %.2f 秒）・通知先 %s%s",
        time.monotonic() - started, result.elapsed, channel, "（予備）" if is_fallback else "",
    )


def build_app():  # noqa: ANN201  Slack の App を返す
    """Slack の App を組み立てる。起動時にだけ設定とトークンを読む。"""
    from slack_bolt import App

    from notifier import post_notification, post_ops_alert
    from routing import load_routing
    from settings import load_settings

    settings = load_settings()
    routing = load_routing()  # 設定の誤りは起動時に止める（黙って届かない状態を作らない）
    app = App(token=settings.slack_bot_token)
    delay = simulated_delay()

    @app.command("/inquiry")
    def on_inquiry(ack, command, respond, client) -> None:  # noqa: ANN001  Bolt が引数名で値を渡す
        handle_inquiry(
            command.get("text", ""),
            command.get("user_id", ""),
            ack,
            respond,
            lambda t: classify(t, settings.gemini_api_key),
            lambda r, t, u: post_notification(client, routing, r, t, u),
            lambda kind, detail, u, t, err=None: post_ops_alert(client, routing, kind, detail, u, t, err),
            delay,
        )

    return app, settings


def main() -> None:
    """Socket Mode で接続して待ち受ける。"""
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app, settings = build_app()
    logger.info("起動：観察用の遅延 %.1f 秒", simulated_delay())
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()

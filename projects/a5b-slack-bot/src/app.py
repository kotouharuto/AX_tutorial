"""A-5b の Slack Bot。Socket Mode で動く（公開 URL 不要）。

【この版は素朴な実装】LLM の分類結果を**待ってから** ack() で応答する。
Slack はスラッシュコマンドに3秒以内の応答を求める（公式ドキュメントで確認）。
分類が3秒を超えると、利用者の画面に operation_timeout が出るはず。
**先に壊れ方を見るため、あえてこの順序で書いている。**

【観察専用の遅延】Gemini の応答が速く3秒に収まると観察できないので、
環境変数 A5B_SIMULATED_DELAY_SEC で分類の前に待たせる（既定は 0）。本番では使わない。

実行：uv run python src/app.py
"""

import logging
import os
import sys
import time
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classifier import ClassificationError, classify  # noqa: E402
from settings import load_settings  # noqa: E402

# ログは標準エラー出力へ。**問い合わせの本文は出さない**（個人情報が入りうる）
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("a5b")

settings = load_settings()
app = App(token=settings.slack_bot_token)


def simulated_delay() -> float:
    """観察専用の遅延（秒）。数値でなければ 0 として扱わず、止める（黙って無視しない）。"""
    raw = os.environ.get("A5B_SIMULATED_DELAY_SEC", "0").strip() or "0"
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"A5B_SIMULATED_DELAY_SEC が数値ではない：{raw!r}") from None


@app.command("/inquiry")
def handle_inquiry(ack, command) -> None:  # noqa: ANN001  Bolt が引数名で値を渡す
    """【素朴な実装】分類が終わってから応答する。"""
    started = time.monotonic()
    text = command.get("text", "")
    logger.info("受信：%d 文字", len(text))

    delay = simulated_delay()
    if delay:
        time.sleep(delay)

    try:
        result = classify(text, settings.gemini_api_key)
        message = (
            f"分類：*{result.category}*　緊急度：*{result.urgency}*\n"
            f"理由：{result.reason}"
        )
        logger.info("分類：%.2f 秒（Gemini %.2f 秒）", time.monotonic() - started, result.elapsed)
    except ClassificationError as exc:
        message = f"分類できなかった：{exc}"
        logger.warning("分類の失敗：%s", exc)

    elapsed = time.monotonic() - started
    logger.info("ack を返す：受信から %.2f 秒（期限は3秒）", elapsed)
    ack(message)  # ← 分類のあとに応答している（素朴な実装）


def main() -> None:
    """Socket Mode で接続して待ち受ける。"""
    logger.info("起動：観察用の遅延 %.1f 秒", simulated_delay())
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()

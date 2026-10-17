"""観察用：Slack の mrkdwn で、日本語の前後に * を置いたとき太字になるかを見比べる。

本番の Bot の代わりに一時的に動かす。/inquiry を1回送ると、書き方を変えた5通りを返す。
実行：uv run python tests/probe_format.py
"""

import sys
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from settings import load_settings  # noqa: E402

ZWSP = "​"  # ゼロ幅スペース（見えない区切り）

VARIANTS = [
    ("1 今の書き方（全角コロン・全角スペースに直接）", "分類：*申請手続き*　緊急度：*低*"),
    ("2 * の前後に半角スペース", "分類： *申請手続き* 　緊急度： *低* "),
    ("3 * の前後にゼロ幅スペース", f"分類：{ZWSP}*申請手続き*{ZWSP}　緊急度：{ZWSP}*低*{ZWSP}"),
    ("4 半角コロンと半角スペース", "分類: *申請手続き*  緊急度: *低*"),
    ("5 行頭から行末まで全体を囲む", "*分類：申請手続き　緊急度：低*"),
]

settings = load_settings()
app = App(token=settings.slack_bot_token)


@app.command("/inquiry")
def probe(ack, respond) -> None:  # noqa: ANN001
    ack("書式の観察：5通りを送ります")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{label}\n{body}"}}
        for label, body in VARIANTS
    ]
    respond(text="書式の観察", blocks=blocks)


if __name__ == "__main__":
    SocketModeHandler(app, settings.slack_app_token).start()

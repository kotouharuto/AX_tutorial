"""Slack に出す文面を組み立てる。Slack に依存しない（テストしやすくするため）。

【* の前後に半角スペースを入れる】`分類：*申請手続き*　緊急度` と書くと、
画面にアスタリスクがそのまま出て太字にならなかった。
**書式記号が全角の「：」や全角スペースに直接くっついていると、mrkdwn として認識されない。**
5通りを見比べて確かめた（tests/probe_format.py）：
  ✗ 全角コロン・全角スペースに直接       ✓ 前後に半角スペース
  ✓ 前後にゼロ幅スペース（見えない文字）  ✓ 半角コロン   ✓ 行頭から行末まで全体を囲む
当初「本文がプレーンテキスト扱いだった」と考えたが誤りだった（blocks の mrkdwn でも同じだった）。

ゼロ幅スペースは見た目が崩れないが採らない。**見えない文字を本文に埋め込む**ことになり、
利用者がコピーした文に紛れ込んで検索や比較が一致しなくなる（A-6a で見えない全角スペースが設定を壊した）。

書式を使う文面は blocks の mrkdwn で送り、text には書式記号の無い代替文を入れる
（text は通知やスクリーンリーダーで使われる）。
"""

from classifier import Classification

ACCEPTED = "受け付けました。分類しています…"
EMPTY_GUIDE = "問い合わせの本文を入れて送ってください。例：/inquiry 経費精算の締め日はいつですか？"


def result_message(result: Classification) -> tuple[str, list[dict]]:
    """分類結果の文面。(代替テキスト, blocks) を返す。"""
    fallback = f"分類：{result.category}　緊急度：{result.urgency}　理由：{result.reason}"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # * の前後は半角スペース（全角文字に直接くっつけると太字にならない）
                "text": (
                    f"分類： *{result.category}* 　緊急度： *{result.urgency}* \n"
                    f"理由：{result.reason}"
                ),
            },
        }
    ]
    return fallback, blocks


def failure_message(reason: str) -> str:
    """分類に失敗したときの文面。利用者が次に何をすればよいかまで書く。

    「受け付けました」を既に出しているので、失敗したことを改めて明確に伝える。
    """
    return (
        f"分類できませんでした（{reason}）。"
        "問い合わせは登録されていません。時間をおいてもう一度送るか、担当者に直接連絡してください。"
    )

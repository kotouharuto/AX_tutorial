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


def failure_message(reason: str, alerted: bool) -> str:
    """分類に失敗したときの文面。利用者が次に何をすればよいかまで書く。

    「受け付けました」を既に出しているので、失敗したことを改めて明確に伝える。
    運用担当に知らせられたかどうかで、利用者に求める行動を変える。
    """
    if alerted:
        return (
            f"分類できませんでした（{reason}）。"
            "運用担当に知らせたので、手で振り分けられます。もう一度送る必要はありません。"
        )
    return (
        f"分類できませんでした（{reason}）。運用担当にも連絡できませんでした。"
        "問い合わせは担当に届いていません。担当者に直接連絡してください。"
    )


def notification_message(
    result: Classification, text: str, user_id: str, is_fallback: bool
) -> tuple[str, list[dict]]:
    """担当チャンネルへの通知の文面。(代替テキスト, blocks) を返す。

    送った人は <@ID> の形でメンションにする（名前を本文に書き写さない）。
    """
    head = "【担当未設定】" if is_fallback else ""
    fallback = f"{head}新しい問い合わせ：{result.category}／緊急度 {result.urgency}"
    body = (
        f"{head}新しい問い合わせ（送信：<@{user_id}>）\n"
        f"分類： *{result.category}* 　緊急度： *{result.urgency}* \n"
        f"理由：{result.reason}"
    )
    if is_fallback:
        body += "\n振り分け先が決まっていない分類のため、ここに届いています。担当を決めてください。"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        # 問い合わせの本文は plain_text で出す（利用者の文の * や _ が書式として解釈されない）
        {"type": "section", "text": {"type": "plain_text", "text": text[:2900]}},
    ]
    return fallback, blocks


def routed_message(channel: str, is_fallback: bool) -> str:
    """利用者に、どこへ通知したかを伝える文面。"""
    if is_fallback:
        return f"担当が決まっていない分類のため、<#{channel}> に回しました。担当者から連絡があります。"
    return f"<#{channel}> の担当に通知しました。"


def notify_failure_message(code: str, alerted: bool) -> str:
    """通知に失敗したことを利用者に伝える文面。"""
    if alerted:
        return (
            f"分類はできましたが、担当への通知に失敗しました（{code}）。"
            "運用担当に知らせたので、手で振り分けられます。もう一度送る必要はありません。"
        )
    return (
        f"分類はできましたが、担当への通知に失敗しました（{code}）。運用担当にも連絡できませんでした。"
        "問い合わせは担当に届いていません。担当者に直接連絡してください。"
    )


# Slack のエラーの種類ごとの直し方。A-5b で実際に踏んだ順に並べている
FIX_HINTS = {
    "missing_scope": (
        "アプリの権限が足りない。マニフェストに権限を足し、**アプリを再インストールする**"
        "（足して保存しただけでは効かない）"
    ),
    "not_in_channel": "Bot が通知先のチャンネルに入っていない。そのチャンネルで `/invite @inquiry-bot`",
    "channel_not_found": "通知先のチャンネルが見つからない。`routing.json` のチャンネル ID を確認する",
    "is_archived": "通知先のチャンネルがアーカイブされている。`routing.json` の通知先を変える",
}


def ops_alert_message(
    kind: str, detail: str, user_id: str, text: str, error: object = None
) -> tuple[str, list[dict]]:
    """運用者のチャンネルに出す失敗の通知。手で対応できるだけの情報を入れる。"""
    code = getattr(error, "code", "")
    lines = [
        f":rotating_light: *{kind}* （送信：<@{user_id}>）",
        f"原因：{detail}",
    ]
    if code in FIX_HINTS:
        lines.append(f"直し方：{FIX_HINTS[code]}")
    needed, provided = getattr(error, "needed", ""), getattr(error, "provided", "")
    if needed or provided:
        lines.append(f"必要な権限：{needed or '不明'}　トークンの権限：{provided or '不明'}")
    lines.append("下の問い合わせを手で振り分けてください。")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "section", "text": {"type": "plain_text", "text": text[:2900] or "（本文なし）"}},
    ]
    return f"{kind}：{detail}", blocks

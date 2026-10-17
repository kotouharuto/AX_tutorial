"""振り分け通知を Slack のチャンネルに投稿する。

【素朴な実装】権限（chat:write）とチャンネルへの参加を前提にしている。
足りないときに何が起きるかを先に見るため、事前の確認は入れていない。
失敗は握り潰さず、Slack が返したエラーの種類（missing_scope など）を例外に入れて上に返す。
"""

from slack_sdk.errors import SlackApiError

from classifier import Classification
from messages import notification_message
from routing import Routing


class NotifyError(RuntimeError):
    """通知に失敗した。code は Slack が返したエラーの種類（missing_scope・not_in_channel など）。

    missing_scope のときは、必要な権限（needed）とトークンが今持っている権限（provided）も持つ。
    **マニフェストに権限を足しても、再インストールするまでトークンの権限は増えない。**
    足す前と後でエラーが同じ missing_scope なので、provided を見ないと区別できない。
    """

    def __init__(self, code: str, channel: str, needed: str = "", provided: str = "") -> None:
        detail = f"（必要：{needed}／トークンの権限：{provided}）" if needed or provided else ""
        super().__init__(f"Slack が {code} を返した（通知先 {channel}）{detail}")
        self.code = code
        self.channel = channel
        self.needed = needed
        self.provided = provided


def post_notification(
    client,  # noqa: ANN001  slack_sdk の WebClient（テストでは偽物を渡す）
    routing: Routing,
    result: Classification,
    text: str,
    user_id: str,
) -> tuple[str, bool]:
    """分類に応じたチャンネルに通知する。(通知先, 予備に回したか) を返す。"""
    channel, is_fallback = routing.resolve(result.category)
    fallback_text, blocks = notification_message(result, text, user_id, is_fallback)
    try:
        client.chat_postMessage(channel=channel, text=fallback_text, blocks=blocks)
    except SlackApiError as exc:
        response = exc.response
        raise NotifyError(
            str(response.get("error", "unknown_error")),
            channel,
            needed=str(response.get("needed", "") or ""),
            provided=str(response.get("provided", "") or ""),
        ) from None
    return channel, is_fallback

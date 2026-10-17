"""振り分けの設定と通知のテスト。Slack には接続しない。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from classifier import Classification  # noqa: E402
from notifier import NotifyError, post_notification  # noqa: E402
from routing import Routing, RoutingError, load_routing  # noqa: E402
from slack_sdk.errors import SlackApiError  # noqa: E402

VALID = {
    "routes": {"システム障害": "C0SYSTEM01", "申請手続き": "C0GENERAL1", "備品・設備": "C0GENERAL1"},
    "fallback": "C0OPS00001",
    "ops": "C0OPS00001",
}
ROUTING = Routing(VALID["routes"], VALID["fallback"], VALID["ops"])


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data,
                    encoding="utf-8")
    return path


# --- 設定の読み込み ------------------------------------------------------------


def test_正しい設定を読める(tmp_path: Path) -> None:
    routing = load_routing(write(tmp_path, VALID))
    assert routing.resolve("システム障害") == ("C0SYSTEM01", False)


def test_対応の無い分類は予備に回す() -> None:
    assert ROUTING.resolve("その他") == ("C0OPS00001", True)


def test_ファイルが無ければ作り方を示す(tmp_path: Path) -> None:
    with pytest.raises(RoutingError, match="routing.example.json"):
        load_routing(tmp_path / "none.json")


def test_JSONとして読めなければ行番号を示す(tmp_path: Path) -> None:
    with pytest.raises(RoutingError, match="行目"):
        load_routing(write(tmp_path, '{"routes": {,}'))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({**VALID, "routes": {"雑談": "C0SYSTEM01"}}, "定義外"),
        ({**VALID, "routes": {"システム障害": "#inq-system"}}, "チャンネル ID の形ではない"),
        ({**VALID, "ops": "C00000000"}, "雛形の値"),  # 形は正しいが、書き換え忘れ
        ({k: v for k, v in VALID.items() if k != "fallback"}, "fallback"),
        ({"fallback": "C0OPS00001", "ops": "C0OPS00001"}, "routes"),
    ],
)
def test_設定の誤りを起動時に見つける(tmp_path: Path, data: dict, message: str | None) -> None:
    """チャンネル名で書く誤り（名前は変わる）や、キーの抜けを止める。"""
    if message is None:
        load_routing(write(tmp_path, data))
        return
    with pytest.raises(RoutingError, match=message):
        load_routing(write(tmp_path, data))


# --- 通知 -----------------------------------------------------------------------


class FakeClient:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.posted: list[dict] = []

    def chat_postMessage(self, **kwargs: object) -> dict:  # noqa: N802  Slack SDK の名前に合わせる
        if self.error == "missing_scope":
            raise SlackApiError(
                "fail",
                {"ok": False, "error": "missing_scope", "needed": "chat:write", "provided": "commands"},
            )
        if self.error:
            raise SlackApiError("fail", {"ok": False, "error": self.error})
        self.posted.append(kwargs)
        return {"ok": True}


RESULT = Classification("システム障害", "高", "VPN に繋がらない", 1.0)


def test_分類に応じたチャンネルに通知する() -> None:
    client = FakeClient()
    assert post_notification(client, ROUTING, RESULT, "VPN に繋がらない", "U0USER0001") == (
        "C0SYSTEM01",
        False,
    )
    sent = client.posted[0]
    assert sent["channel"] == "C0SYSTEM01"
    assert "<@U0USER0001>" in sent["blocks"][0]["text"]["text"]
    assert sent["blocks"][1]["text"]["type"] == "plain_text", "本文は書式として解釈させない"


def test_予備に回した通知には担当未設定と書く() -> None:
    client = FakeClient()
    other = Classification("その他", "低", "x", 1.0)
    post_notification(client, ROUTING, other, "x", "U0USER0001")
    assert "担当未設定" in client.posted[0]["text"]


@pytest.mark.parametrize("code", ["missing_scope", "not_in_channel", "channel_not_found"])
def test_Slackのエラーの種類を握り潰さず返す(code: str) -> None:
    with pytest.raises(NotifyError) as exc:
        post_notification(FakeClient(error=code), ROUTING, RESULT, "x", "U0USER0001")
    assert exc.value.code == code
    assert exc.value.channel == "C0SYSTEM01"



def test_雛形のファイルをそのまま使うと止まる(tmp_path: Path) -> None:
    """routing.example.json をコピーしただけの状態を通さない。"""
    example = Path(__file__).resolve().parent.parent / "routing.example.json"
    with pytest.raises(RoutingError, match="雛形の値"):
        load_routing(example)



def test_権限不足のときは必要な権限と今の権限を残す() -> None:
    """マニフェストに足しても再インストール前は provided に出てこない。これで区別できる。"""
    with pytest.raises(NotifyError) as exc:
        post_notification(FakeClient(error="missing_scope"), ROUTING, RESULT, "x", "U0USER0001")
    assert exc.value.needed == "chat:write"
    assert exc.value.provided == "commands"
    assert "トークンの権限：commands" in str(exc.value)

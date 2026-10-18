"""Bot の処理の順序のテスト。Slack と Gemini には接続しない。

**ack を最初に呼ぶこと**を固定する。素朴な実装（分類が終わってから ack）は
3秒の期限を超えて「失敗しました。もう一度試すか…」と出し、遅れて結果も出していた。
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app as app_mod  # noqa: E402
from classifier import Classification, ClassificationError  # noqa: E402
from messages import ACCEPTED, EMPTY_GUIDE  # noqa: E402

RESULT = Classification("申請手続き", "低", "締め日の確認", 2.8)


def notify_ok(result: Classification, text: str, user_id: str) -> tuple[str, bool]:
    """通知が成功する偽物。"""
    return "C0SYSTEM01", False


class Alerts:
    """運用者への通知を記録する偽物。ok=False なら送れなかったことにする。"""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple] = []

    def __call__(self, kind: str, detail: str, user_id: str, text: str, error: object = None) -> bool:
        self.sent.append((kind, detail, user_id, text, error))
        return self.ok


def run(  # noqa: ANN001
    text: str, rec: "Recorder", classify_fn, notify_fn=notify_ok, delay: float = 0.0, alerts=None
) -> "Alerts":
    alerts = alerts if alerts is not None else Alerts()
    app_mod.handle_inquiry(
        text, "U0USER0001", rec.ack, rec.respond, classify_fn, notify_fn, alerts, delay
    )
    return alerts


class Recorder:
    """ack と respond の呼ばれた順序と時刻を記録する。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float, dict]] = []
        self.started = time.monotonic()

    def ack(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("ack", time.monotonic() - self.started, {"args": args, **kwargs}))

    def respond(self, **kwargs: object) -> None:
        self.calls.append(("respond", time.monotonic() - self.started, kwargs))


def test_ackを分類より先に呼ぶ() -> None:
    rec = Recorder()

    def slow_classify(text: str) -> Classification:
        time.sleep(0.3)  # 分類に時間がかかる状況
        rec.calls.append(("classify", time.monotonic() - rec.started, {}))
        return RESULT

    run("経費精算の締め日は？", rec, slow_classify)
    assert [c[0] for c in rec.calls] == ["ack", "classify", "respond"]
    assert rec.calls[0][2]["args"] == (ACCEPTED,)
    assert rec.calls[0][1] < 0.1, "ack は分類を待たずにすぐ返す"


def test_分類が遅くてもackは遅れない() -> None:
    """観察用の遅延を入れても ack は即時。素朴な実装ではここが期限を超えていた。"""
    rec = Recorder()
    run("x", rec, lambda t: RESULT, delay=0.5)
    ack_time = next(c[1] for c in rec.calls if c[0] == "ack")
    respond_time = next(c[1] for c in rec.calls if c[0] == "respond")
    assert ack_time < 0.1
    assert respond_time >= 0.5


def test_結果はmrkdwnのblocksで送り代替テキストに書式記号を入れない() -> None:
    """素朴な実装ではアスタリスクが画面にそのまま出た。"""
    rec = Recorder()
    run("x", rec, lambda t: RESULT)
    sent = rec.calls[-1][2]
    assert sent["blocks"][0]["text"]["type"] == "mrkdwn"
    assert "*申請手続き*" in sent["blocks"][0]["text"]["text"]
    assert "*" not in sent["text"].split("<#")[0], "代替テキスト（通知に出る）に書式記号を入れない"


def test_分類の失敗は改めて利用者に伝える() -> None:
    """「受け付けました」を出した後なので、失敗したことを明確に伝える。"""
    rec = Recorder()

    def failing(text: str) -> Classification:
        raise ClassificationError("Gemini が HTTP 402 を返した")

    alerts = run("x", rec, failing)
    message = rec.calls[-1][2]["text"]
    assert "分類できませんでした" in message
    assert "402" in message
    assert "運用担当に知らせた" in message
    assert alerts.sent[0][0] == "分類の失敗"


def test_本文が空なら分類せず案内だけ返す() -> None:
    rec = Recorder()

    def must_not_call(text: str) -> Classification:
        raise AssertionError("空の本文で分類を呼んではいけない")

    run("   ", rec, must_not_call)
    assert [c[0] for c in rec.calls] == ["ack"]
    assert rec.calls[0][2]["args"] == (EMPTY_GUIDE,)


@pytest.mark.parametrize(("raw", "expected"), [("", 0.0), ("4", 4.0), ("0.5", 0.5)])
def test_観察用の遅延を読む(raw: str, expected: float, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A5B_SIMULATED_DELAY_SEC", raw)
    assert app_mod.simulated_delay() == expected


def test_観察用の遅延が数値でなければ止める(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A5B_SIMULATED_DELAY_SEC", "四")
    with pytest.raises(SystemExit):
        app_mod.simulated_delay()



def test_太字の記号の前後は半角スペースか行の端() -> None:
    """全角の「：」や全角スペースに * が直接くっつくと、Slack で太字にならない（実機で確認）。"""
    import re

    from messages import result_message

    _, blocks = result_message(RESULT)
    text = blocks[0]["text"]["text"]
    for match in re.finditer(r"\*[^*\n]+\*", text):
        before = text[match.start() - 1] if match.start() > 0 else "\n"
        after = text[match.end()] if match.end() < len(text) else "\n"
        assert before in " \n", f"開きの * の前が {before!r}"
        assert after in " \n", f"閉じの * の後ろが {after!r}"


def test_見えない文字を本文に入れない() -> None:
    """ゼロ幅スペースでも太字になるが、コピーした文に紛れ込むので使わない。"""
    from messages import result_message

    fallback, blocks = result_message(RESULT)
    for text in (fallback, blocks[0]["text"]["text"]):
        assert "\u200b" not in text



def test_通知先を利用者に伝える() -> None:
    rec = Recorder()
    run("x", rec, lambda t: RESULT)
    sent = rec.calls[-1][2]
    assert "<#C0SYSTEM01>" in sent["text"]
    assert sent["blocks"][-1]["type"] == "context"


def test_通知に失敗したら担当に届いていないと伝える() -> None:
    """【素朴な実装】利用者には伝える。運用者への通知は到達条件4で足す。"""
    from notifier import NotifyError

    rec = Recorder()

    def failing_notify(result: Classification, text: str, user_id: str) -> tuple[str, bool]:
        raise NotifyError("missing_scope", "C0SYSTEM01")

    run("x", rec, lambda t: RESULT, notify_fn=failing_notify)
    message = rec.calls[-1][2]["text"]
    assert "missing_scope" in message
    assert "通知に失敗しました" in message


def test_分類に失敗したら通知しない() -> None:
    rec = Recorder()

    def failing(text: str) -> Classification:
        raise ClassificationError("x")

    def must_not_notify(result: Classification, text: str, user_id: str) -> tuple[str, bool]:
        raise AssertionError("分類に失敗したのに通知してはいけない")

    run("x", rec, failing, notify_fn=must_not_notify)



def test_通知の失敗は画面に出るblocksに入れる() -> None:
    """**blocks があると text は画面に表示されない。** 失敗を text にだけ入れると、
    利用者には分類結果しか見えず「担当に届いた」と思い込む（実機で起きた）。"""
    from notifier import NotifyError

    rec = Recorder()

    def failing_notify(result: Classification, text: str, user_id: str) -> tuple[str, bool]:
        raise NotifyError("missing_scope", "C0SYSTEM01")

    run("x", rec, lambda t: RESULT, notify_fn=failing_notify)
    shown = " ".join(b["text"]["text"] for b in rec.calls[-1][2]["blocks"] if "text" in b)
    assert "missing_scope" in shown, "失敗が画面に出る blocks に入っていない"
    assert "通知に失敗しました" in shown


def test_画面に出す情報はすべてblocksにある() -> None:
    """成功時も、通知先の案内が blocks（context）にあること。"""
    rec = Recorder()
    run("x", rec, lambda t: RESULT)
    blocks = rec.calls[-1][2]["blocks"]
    shown = " ".join(
        e["text"] for b in blocks for e in b.get("elements", []) if "text" in e
    ) + " ".join(b["text"]["text"] for b in blocks if "text" in b)
    assert "<#C0SYSTEM01>" in shown



# --- 到達条件4：失敗時の通知経路 ------------------------------------------------


def test_通知に失敗したら運用者に原因付きで知らせる() -> None:
    from notifier import NotifyError

    rec = Recorder()
    error = NotifyError("not_in_channel", "C0SYSTEM01")

    def failing_notify(result: Classification, text: str, user_id: str) -> tuple[str, bool]:
        raise error

    alerts = run("VPN に繋がらない", rec, lambda t: RESULT, notify_fn=failing_notify)
    kind, detail, user_id, text, err = alerts.sent[0]
    assert kind == "通知の失敗"
    assert "not_in_channel" in detail
    assert (user_id, text, err) == ("U0USER0001", "VPN に繋がらない", error)
    shown = " ".join(b["text"]["text"] for b in rec.calls[-1][2]["blocks"] if "text" in b)
    assert "運用担当に知らせた" in shown


def test_運用者への通知も失敗したら利用者に直接連絡を求める() -> None:
    """最後の手段。利用者に「届いていない」と明確に伝える。"""
    rec = Recorder()

    def failing(text: str) -> Classification:
        raise ClassificationError("Gemini が HTTP 402 を返した")

    run("x", rec, failing, alerts=Alerts(ok=False))
    message = rec.calls[-1][2]["text"]
    assert "運用担当にも連絡できませんでした" in message
    assert "担当者に直接連絡" in message


def test_成功したときは運用者に知らせない() -> None:
    rec = Recorder()
    alerts = run("x", rec, lambda t: RESULT)
    assert alerts.sent == []

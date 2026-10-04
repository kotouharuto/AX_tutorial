"""シート参照のテスト。手元に**偽の GAS** を立てて、実際の HTTP で確かめる。

偽の GAS は本物の振る舞いを真似る：
- POST /exec を受けると 302 で /echo にリダイレクトし、/echo への GET で応答を返す
- ステータスは常に 200。成否は本文の ok で表す
"""

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server as server_mod  # noqa: E402
from sheet import SheetError, fetch_inquiries  # noqa: E402

TOKEN = "test-token-0123456789"

ROWS = [
    {"timestamp": "2026-09-01T10:00:00+09:00", "content": "VPN に繋がらない",
     "category": "システム障害", "urgency": "高", "status": "完了", "detail": ""},
    {"timestamp": "2026-09-02T11:00:00+09:00", "content": "経費精算の締め日は？",
     "category": "申請手続き", "urgency": "低", "status": "未分類", "detail": "担当者未設定"},
]


class FakeGas(BaseHTTPRequestHandler):
    """本物の GAS の挙動を真似る偽サーバ。mode で返す内容を切り替える。"""

    mode = "ok"
    last_body: dict | None = None
    last_path: str = ""

    def log_message(self, *args: object) -> None:  # テスト出力を汚さない
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        FakeGas.last_body = json.loads(self.rfile.read(length) or b"{}")
        FakeGas.last_path = self.path
        # 本物の GAS と同じく、POST の応答は 302 で別の URL から返す
        self.send_response(302)
        self.send_header("Location", "/echo")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        body = FakeGas.last_body or {}
        if FakeGas.mode == "html":
            # 公開範囲の設定ミスなどで、ログイン画面が 200 で返る状況を真似る
            self._send(200, "<!DOCTYPE html><html><body>Sign in</body></html>", "text/html")
            return
        if FakeGas.mode == "no_ok":
            self._send(200, json.dumps({"rows": []}), "application/json")
            return
        if body.get("token") != TOKEN:
            self._send(200, json.dumps({"ok": False, "error": "認証に失敗した"}), "application/json")
            return
        rows = [r for r in ROWS if not body.get("status") or r["status"] == body["status"]]
        payload = {"ok": True, "total": len(rows), "returned": len(rows), "rows": rows}
        self._send(200, json.dumps(payload, ensure_ascii=False), "application/json")

    def _send(self, code: int, text: str, ctype: str) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def gas_url() -> Iterator[str]:
    """偽の GAS を起動して URL を返す。"""
    FakeGas.mode = "ok"
    httpd = HTTPServer(("127.0.0.1", 0), FakeGas)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/exec"
    httpd.shutdown()


# --- sheet.py（HTTP の処理） ---------------------------------------------------


def test_リダイレクトを辿って取得できる(gas_url: str) -> None:
    """POST → 302 → GET の流れで応答を受け取れること（本物の GAS と同じ経路）。"""
    result = fetch_inquiries(gas_url, TOKEN)
    assert result.total == 2
    assert [r["category"] for r in result.rows] == ["システム障害", "申請手続き"]


def test_トークンは本文で送りURLに載せない(gas_url: str) -> None:
    fetch_inquiries(gas_url, TOKEN)
    assert FakeGas.last_body["token"] == TOKEN
    assert TOKEN not in FakeGas.last_path, "トークンが URL に載っている"


def test_絞り込みの条件が届く(gas_url: str) -> None:
    result = fetch_inquiries(gas_url, TOKEN, status="未分類")
    assert FakeGas.last_body["status"] == "未分類"
    assert result.total == 1


def test_トークン違いは理由付きの失敗(gas_url: str) -> None:
    """**ステータスは 200 でも失敗**。ok を見て判定すること。"""
    with pytest.raises(SheetError, match="認証に失敗した"):
        fetch_inquiries(gas_url, "wrong-token")


def test_HTMLが返ったら成功扱いしない(gas_url: str) -> None:
    """200 で HTML（ログイン画面など）が返る状況。成功に見えるので特に注意。"""
    FakeGas.mode = "html"
    with pytest.raises(SheetError, match="JSON ではなかった（HTML"):
        fetch_inquiries(gas_url, TOKEN)


def test_okが無い応答は想定外として扱う(gas_url: str) -> None:
    FakeGas.mode = "no_ok"
    with pytest.raises(SheetError, match="ok が無い"):
        fetch_inquiries(gas_url, TOKEN)


def test_接続できない場合() -> None:
    with pytest.raises(SheetError, match="接続できない"):
        fetch_inquiries("http://127.0.0.1:9/exec", TOKEN, timeout=2)


def test_エラー文にトークンが含まれない(gas_url: str) -> None:
    """失敗時のメッセージは Claude に届く。トークンを混ぜない。"""
    for mode in ("html", "no_ok"):
        FakeGas.mode = mode
        with pytest.raises(SheetError) as exc:
            fetch_inquiries(gas_url, TOKEN)
        assert TOKEN not in str(exc.value)


# --- server.py（MCP のツールとして） ---------------------------------------------


async def call(name: str, args: dict) -> object:
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return await server_mod.server.call_tool(name, args)
    except ToolError as exc:
        return exc


async def test_ツールとして呼ぶと整形して返る(gas_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A6A_SHEET_API_URL", gas_url)
    monkeypatch.setenv("A6A_SHEET_API_TOKEN", TOKEN)
    result = await call("list_inquiries", {"limit": 10})
    text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
    assert "2 件中 2 件" in text
    assert "VPN に繋がらない" in text


async def test_未設定なら不足している変数名が届く(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A6A_SHEET_API_URL", raising=False)
    monkeypatch.delenv("A6A_SHEET_API_TOKEN", raising=False)
    exc = await call("list_inquiries", {})
    assert "A6A_SHEET_API_URL" in str(exc) and "A6A_SHEET_API_TOKEN" in str(exc)


async def test_シート側の失敗が原因付きで届く(gas_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A6A_SHEET_API_URL", gas_url)
    monkeypatch.setenv("A6A_SHEET_API_TOKEN", "wrong-token")
    exc = await call("list_inquiries", {})
    assert "認証に失敗した" in str(exc)
    assert "wrong-token" not in str(exc), "トークンがエラー文に出ている"


@pytest.mark.parametrize("limit", [0, 51])
async def test_limitの範囲外は理由付き(limit: int) -> None:
    exc = await call("list_inquiries", {"limit": limit})
    assert "1〜50" in str(exc)

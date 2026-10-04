"""問い合わせ記録シート（GAS のウェブアプリ）への問い合わせ。MCP に依存しない。

【GAS 側の仕様による制約】
- HTTP ヘッダを受け取れないので、トークンは **POST の本文**で送る
- ステータスコードは常に 200。**成否は本文の ok で判定する**（ステータスでは分からない）
- POST すると 302 で別の URL にリダイレクトされ、そこから GET で応答を受け取る
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

TIMEOUT = 30
MAX_LIMIT = 50


class SheetError(Exception):
    """シートを読めない。**利用者が対処できる原因**を message に入れる。トークンは含めない。"""


@dataclass(frozen=True)
class SheetResult:
    """取得結果。total は条件に一致した全件数、rows は返ってきた分だけ。"""

    total: int
    rows: list[dict]


def fetch_inquiries(
    url: str,
    token: str,
    status: str | None = None,
    category: str | None = None,
    limit: int = 20,
    timeout: float = TIMEOUT,
) -> SheetResult:
    """問い合わせ記録を取得する。失敗は SheetError にまとめる。"""
    body: dict = {"token": token, "limit": limit}
    if status:
        body["status"] = status
    if category:
        body["category"] = category

    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SheetError(f"シート API が HTTP {exc.code} を返した。URL が正しいか確認すること") from None
    except urllib.error.URLError as exc:
        raise SheetError(f"シート API に接続できない（{exc.reason}）。URL とネットワークを確認すること") from None
    except TimeoutError:
        raise SheetError(f"シート API が {timeout} 秒以内に応答しなかった") from None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # 何が返ってきたかの手がかりだけ示す（中身は返さない）
        kind = "HTML" if raw.lstrip().startswith("<") else "JSON 以外の文字列"
        raise SheetError(
            f"シート API の応答が JSON ではなかった（{kind}・Content-Type: {content_type or '不明'}）。"
            "ウェブアプリの公開範囲とデプロイの URL を確認すること"
        ) from None

    # ステータスは常に 200 なので、成否は ok で見る
    if not isinstance(payload, dict) or "ok" not in payload:
        raise SheetError("シート API の応答に ok が無い。GAS 側のコードが想定と違う")
    if payload["ok"] is not True:
        raise SheetError(f"シート API がエラーを返した：{payload.get('error', '理由不明')}")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise SheetError("シート API の応答に rows が無い。GAS 側のコードが想定と違う")
    return SheetResult(total=int(payload.get("total", len(rows))), rows=rows)

"""問い合わせの分類（Gemini）。A-1 と同じプロンプト・同じモデルにする。

【A-1 のコードを import しない理由】A-1 は GAS（JavaScript）で、プロジェクト間で import しない規約。
プロンプトと検査の考え方を Python に写している。

【A-1 から引き継ぐこと】
- JSON で返させてパースする。自然文で返させると表記ゆれで必ず壊れる
- それでも壊れる前提で、コードフェンス除去の予備を入れる
- 分類と緊急度は決めた値以外を受け付けない
- API キーはヘッダで渡す（URL に載せるとログやエラー文に残る）
"""

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# A-1 の Config.js と同じ。モデル名は時間で腐るので1か所に置く（A-1 で 404 を踏んだ）
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)
CATEGORIES = ("システム障害", "申請手続き", "備品・設備", "その他")
URGENCIES = ("高", "中", "低")
TIMEOUT = 30


class ClassificationError(RuntimeError):
    """分類できなかった。**利用者に見せてよい文言**だけを入れる（API キーや本文は入れない）。"""


@dataclass(frozen=True)
class Classification:
    """分類結果。elapsed は API 呼び出しにかかった秒数（応答期限の観察に使う）。"""

    category: str
    urgency: str
    reason: str
    elapsed: float


def build_prompt(inquiry: str) -> str:
    """A-1 の buildClassificationPrompt_ と同じ文面。"""
    return "\n".join(
        [
            "あなたは社内問い合わせの振り分け担当です。以下の問い合わせを分類してください。",
            "",
            f"分類は次のいずれか1つ：{' / '.join(CATEGORIES)}",
            f"緊急度は次のいずれか1つ：{' / '.join(URGENCIES)}",
            "",
            "出力は JSON のみ。前置き・説明・コードフェンスを一切含めないこと。",
            '形式：{"category": "...", "urgency": "...", "reason": "30字以内の判断理由"}',
            "",
            "--- 問い合わせ ---",
            inquiry,
        ]
    )


def parse_json_loosely(text: str) -> dict:
    """JSON を読む。失敗したらコードフェンスと前後の文を除いてもう一度試す。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # ```json ... ``` で囲まれている場合
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # 前後に説明文が付いている場合：最初の { から最後の } まで
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ClassificationError("分類結果を JSON として読めなかった")


def validate(parsed: object) -> tuple[str, str, str]:
    """決めた値以外を受け付けない。"""
    if not isinstance(parsed, dict):
        raise ClassificationError("分類結果の形が想定と違う（JSON のオブジェクトではない）")
    category = str(parsed.get("category", "")).strip()
    urgency = str(parsed.get("urgency", "")).strip()
    reason = str(parsed.get("reason", "")).strip()
    if category not in CATEGORIES:
        raise ClassificationError(f"分類が定義外：{category!r}")
    if urgency not in URGENCIES:
        raise ClassificationError(f"緊急度が定義外：{urgency!r}")
    return category, urgency, reason


def call_gemini(prompt: str, api_key: str, timeout: float = TIMEOUT) -> str:
    """Gemini を呼び、生成テキストを返す。"""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        # JSON で返させ、温度を下げる（A-1 と同じ）
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    request = urllib.request.Request(
        GEMINI_ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 本文には原因が書かれているが、利用者に見せる文言にはステータスだけを入れる
        raise ClassificationError(f"Gemini が HTTP {exc.code} を返した") from None
    except urllib.error.URLError as exc:
        raise ClassificationError(f"Gemini に接続できない（{exc.reason}）") from None
    except TimeoutError:
        raise ClassificationError(f"Gemini が {timeout} 秒以内に応答しなかった") from None
    except json.JSONDecodeError:
        raise ClassificationError("Gemini の応答が JSON ではなかった") from None

    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        # 安全性の判定で止められた場合などは候補が空になる
        raise ClassificationError("Gemini の応答に生成結果が無かった") from None


def classify(inquiry: str, api_key: str) -> Classification:
    """問い合わせを分類する。失敗は ClassificationError にまとめる。"""
    if not inquiry.strip():
        raise ClassificationError("問い合わせの本文が空")
    started = time.monotonic()
    raw = call_gemini(build_prompt(inquiry), api_key)
    category, urgency, reason = validate(parse_json_loosely(raw))
    return Classification(category, urgency, reason, time.monotonic() - started)

"""分類処理のテスト。Gemini には接続しない（urlopen を差し替える）。"""

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import classifier  # noqa: E402
from classifier import (  # noqa: E402
    ClassificationError,
    build_prompt,
    classify,
    parse_json_loosely,
    validate,
)

KEY = "test-api-key-0123456789"


def gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *a: object) -> None:
        return None


def fake_urlopen(payload: object, captured: dict | None = None):
    def _urlopen(request, timeout=0):  # noqa: ANN001
        if captured is not None:
            captured["request"] = request
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    return _urlopen


# --- プロンプト ---------------------------------------------------------------


def test_プロンプトはA1と同じ選択肢を示す() -> None:
    prompt = build_prompt("経費精算の締め日は？")
    assert "システム障害 / 申請手続き / 備品・設備 / その他" in prompt
    assert "高 / 中 / 低" in prompt
    assert prompt.endswith("経費精算の締め日は？")


# --- JSON の読み取り ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"category": "その他", "urgency": "低", "reason": "x"}',
        '```json\n{"category": "その他", "urgency": "低", "reason": "x"}\n```',
        '結果です：{"category": "その他", "urgency": "低", "reason": "x"} 以上',
    ],
)
def test_コードフェンスや前後の文があっても読める(text: str) -> None:
    assert parse_json_loosely(text)["category"] == "その他"


def test_JSONで読めなければ例外() -> None:
    with pytest.raises(ClassificationError, match="JSON として読めなかった"):
        parse_json_loosely("分類はその他です")


@pytest.mark.parametrize(
    ("parsed", "message"),
    [
        ([], "オブジェクトではない"),
        ({"category": "雑談", "urgency": "低"}, "分類が定義外"),
        ({"category": "その他", "urgency": "最高"}, "緊急度が定義外"),
    ],
)
def test_決めた値以外は受け付けない(parsed: object, message: str) -> None:
    with pytest.raises(ClassificationError, match=message):
        validate(parsed)


# --- Gemini の呼び出し ------------------------------------------------------------


def test_分類できる(monkeypatch: pytest.MonkeyPatch) -> None:
    body = '{"category": "申請手続き", "urgency": "低", "reason": "締め日の確認"}'
    monkeypatch.setattr(classifier.urllib.request, "urlopen", fake_urlopen(gemini_response(body)))
    result = classify("経費精算の締め日は？", KEY)
    assert (result.category, result.urgency) == ("申請手続き", "低")
    assert result.elapsed >= 0


def test_APIキーはヘッダで送りURLに載せない(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    body = '{"category": "その他", "urgency": "低", "reason": "x"}'
    monkeypatch.setattr(
        classifier.urllib.request, "urlopen", fake_urlopen(gemini_response(body), captured)
    )
    classify("テスト", KEY)
    request = captured["request"]
    assert request.get_header("X-goog-api-key") == KEY
    assert KEY not in request.full_url


def test_HTTPエラーは原因を示しキーを含めない(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(request, timeout=0):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(classifier.urllib.request, "urlopen", failing)
    with pytest.raises(ClassificationError) as exc:
        classify("テスト", KEY)
    assert "404" in str(exc.value)
    assert KEY not in str(exc.value)


def test_生成結果が無い応答は失敗にする(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier.urllib.request, "urlopen", fake_urlopen({"candidates": []}))
    with pytest.raises(ClassificationError, match="生成結果が無かった"):
        classify("テスト", KEY)


def test_空の本文は送らない() -> None:
    with pytest.raises(ClassificationError, match="空"):
        classify("   ", KEY)

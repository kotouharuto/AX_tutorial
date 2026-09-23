"""自作RAG：回答生成（Gemini）。

リトライ設計は A-1 で作ったものを移植している
（→ docs/pitfalls/a1-external-api-retry-design.md）。
**再試行する条件より、再試行しない条件の方が本体。**
"""

import os
import random
import time
from pathlib import Path

import requests

from config import GEMINI_ENDPOINT
from rag import Chunk

RETRY_MAX_ATTEMPTS = 4
RETRY_BASE_SEC = 1.0

# 既製方式（NotebookLM / Claude Projects）に投げたものと**同じ前置き**を使う。
# 方式ごとにプロンプトを変えると条件が揃わず、比較にならない。
SYSTEM_NOTE = """以下は社内文書についての質問です。
アップロードされた文書のみを根拠に答えてください。
文書に記載がない場合は、推測せず「文書に記載がありません」と答えてください。
"""


def load_api_key() -> str:
    """API キーを環境変数または .env から取得する。

    キーをコードに書かない。ログにも出さない。
    """
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return validate_api_key(key)

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return validate_api_key(line.split("=", 1)[1].strip().strip('"').strip("'"))

    raise RuntimeError(
        "GEMINI_API_KEY が未設定です。\n"
        f"  {env_path} に GEMINI_API_KEY=<キー> を書くか、環境変数に設定してください。\n"
        "  （.env は .gitignore 済みです）"
    )


def validate_api_key(key: str) -> str:
    """API キーの形式を検証する。

    HTTP ヘッダは latin-1 でエンコードされるため、非 ASCII 文字が含まれていると
    リクエスト送信時に UnicodeEncodeError になる。**エラーが出る場所が
    requests の内部なので、原因が「キーの中身」だと気づきにくい。**

    手順書のプレースホルダ（「あなたのキー」等）をそのまま貼ってしまう事故は
    実際に起きるので、使う前に弾く。
    """
    if not key.isascii():
        raise RuntimeError(
            "GEMINI_API_KEY に日本語などの非 ASCII 文字が含まれています。\n"
            "  手順書のプレースホルダをそのまま貼っていないか確認してください。\n"
            "  （HTTP ヘッダは latin-1 でしか送れないため、送信時にエラーになります）"
        )
    if len(key) < 20:
        raise RuntimeError(
            f"GEMINI_API_KEY が短すぎます（{len(key)}文字）。値が正しいか確認してください。"
        )
    return key


def build_prompt(question: str, chunks: list[Chunk]) -> str:
    """検索結果を文脈として与えるプロンプトを組み立てる。

    出典（文書名）を必ず添える。どこから答えたかを追えないと、
    誤答したときに検索の問題か生成の問題か切り分けられない。
    """
    context = "\n\n".join(
        f"--- 出典: {c.doc_name} ---\n{c.text}" for c in chunks
    )
    return f"""{SYSTEM_NOTE}
以下は検索で見つかった社内文書の抜粋です。

{context}

--- 質問 ---
{question}

回答（根拠にした出典の文書名も示すこと）："""


def ask_gemini(prompt: str, api_key: str) -> str:
    """Gemini に問い合わせる。一時障害は指数バックオフで再試行する。"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    last_error = None

    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        response = requests.post(
            GEMINI_ENDPOINT,
            # キーはクエリ文字列ではなくヘッダで渡す（URL に載せるとログに残る）
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )

        if response.status_code == 200:
            body = response.json()
            candidates = body.get("candidates") or []
            if not candidates:
                raise RuntimeError(f"応答に候補がありません: {str(body)[:300]}")
            parts = candidates[0].get("content", {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts).strip()

        detail = f"ステータス {response.status_code}（試行 {attempt}/{RETRY_MAX_ATTEMPTS}）: {response.text[:400]}"

        # 4xx はこちらの誤り。再試行しても直らないので即座に諦める。
        if not (response.status_code == 429 or 500 <= response.status_code < 600):
            raise RuntimeError(f"回復不能なエラー。{detail}")

        last_error = RuntimeError(f"一時エラー。{detail}")
        if attempt < RETRY_MAX_ATTEMPTS:
            # ジッターを入れる（揃っていると再試行も揃って再び衝突する）
            wait = RETRY_BASE_SEC * (2 ** (attempt - 1)) * (0.5 + random.random())
            print(f"    {wait:.1f}秒待って再試行 ({detail[:60]}...)")
            time.sleep(wait)

    raise last_error  # 諦める。無限リトライは書かない。

"""Dify のアプリ API で30問を一括投入し、回答を記録する。

【会話履歴の扱い】
各問を**独立した会話**として投げる（conversation_id を引き継がない）。
自作RAG と同条件になり、直前の回答に引きずられる偶発的な影響を排除できる。
NotebookLM / Claude Projects は1つの会話で順に投げたため、この点は条件が違う。
比較のときに明記すること。

【採点】
自動採点はしない。A-2 で自動判定が誤答を正解と判定した実績があるため
（→ docs/pitfalls/a2-auto-scoring-cannot-be-trusted.md）。
回答と引用文書を記録し、採点は eval/results/dify.yaml に手で書く。
"""

import random
import sys
import time
from pathlib import Path

import requests
import yaml

PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_DIR / ".env"
EVAL_DIR = PROJECT_DIR / "eval"
OUT_PATH = EVAL_DIR / "results" / "dify_raw.yaml"

BASE_URL = "http://localhost:8080/v1"
SEED = 20260901  # make_prompts.py と同じ。投入順を揃える。


def load_key() -> str:
    """アプリ API キーを .env から読む。プレースホルダ事故を弾く。"""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("DIFY_APP_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not key.isascii():
                raise RuntimeError("DIFY_APP_API_KEY に非 ASCII 文字が含まれています。プレースホルダのままではありませんか。")
            if not key.startswith("app-"):
                raise RuntimeError(f"DIFY_APP_API_KEY は 'app-' で始まるはずです（先頭: {key[:6]!r}）。ナレッジ用の dataset- キーとは別物です。")
            return key
    raise RuntimeError(f"{ENV_PATH} に DIFY_APP_API_KEY=app-... を追記してください。")


def load_questions_in_order() -> list[dict]:
    """questions.yaml を make_prompts.py と同じ順序に並べる（none が連続しない後処理込み）。"""
    data = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    order = list(data["questions"])
    random.Random(SEED).shuffle(order)
    for i in range(1, len(order)):
        if order[i]["type"] != "none" or order[i - 1]["type"] != "none":
            continue
        for j in range(i + 1, len(order)):
            prev_ok = order[j - 1]["type"] != "none"
            next_ok = j + 1 >= len(order) or order[j + 1]["type"] != "none"
            if order[j]["type"] != "none" and prev_ok and next_ok:
                order[i], order[j] = order[j], order[i]
                break
    return order


def ask(key: str, question: str) -> dict:
    """1問を新規会話として投げ、回答と引用文書を返す。"""
    res = requests.post(
        f"{BASE_URL}/chat-messages",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"inputs": {}, "query": question, "response_mode": "blocking", "user": "a2-eval"},
        timeout=120,
    )
    if not res.ok:
        raise RuntimeError(f"{res.status_code}: {res.text[:400]}")
    body = res.json()
    sources = sorted({
        r.get("document_name", "").split("_", 1)[0]
        for r in body.get("metadata", {}).get("retriever_resources", [])
    })
    return {"answer": body.get("answer", "").strip(), "retrieved": sources}


def main() -> None:
    """30問を投げて dify_raw.yaml に保存する。"""
    key = load_key()
    order = load_questions_in_order()
    print(f"{len(order)} 問を各問独立の会話として投入する\n")

    rows = []
    for i, q in enumerate(order, 1):
        try:
            result = ask(key, q["question"])
        except RuntimeError as e:
            print(f"  [{i:02d}] {q['id']} 失敗: {e}")
            sys.exit(1)
        rows.append({
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "retrieved": result["retrieved"],
            "answer": result["answer"],
            "score": None,  # 手で採点する
            "note": "",
        })
        preview = result["answer"].replace("\n", " ")[:70]
        print(f"  [{i:02d}] {q['id']:<4} {','.join(result['retrieved'])[:30]:<30} {preview}")
        time.sleep(0.5)

    OUT_PATH.write_text(
        yaml.dump({"method": "dify", "conversation": "independent", "answers": rows},
                  allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"\n→ {OUT_PATH}")
    print("score は未記入。回答を読んで手で採点し、eval/results/dify.yaml に転記すること。")


if __name__ == "__main__":
    main()

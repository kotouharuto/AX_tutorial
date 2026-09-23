"""自作RAG：30問を各構成で実行し、結果を記録する。

【自動判定について】
210回答（30問 × 7構成）を手で採点するのは現実的でないため、
expected に含まれる数値・キーワードとの照合で自動判定する。

**自動判定は目安。** ベースライン構成だけは目視で検算し、
自動判定がどれだけずれるかを把握してから相対比較に使う。
"""

import argparse
import re
import time
from pathlib import Path

import yaml

from answer import ask_gemini, build_prompt, load_api_key
from config import EVAL_DIR, VARIANTS, Variant
from rag import build_index, load_documents

RESULTS_DIR = Path(__file__).parent / "results"

# 「記載がない」と答えたと見なす表現
NO_ANSWER_PATTERNS = ["記載がありません", "記載がない", "記載されていません", "見当たりません", "情報がありません"]


def extract_keys(expected: str) -> list[str]:
    """expected から判定用のキー（数値・金額・日数）を抜き出す。

    数値は表記ゆれ（12,000 / 12000）を吸収して比較する。
    """
    keys = re.findall(r"\d[\d,]*", expected)
    return [k.replace(",", "") for k in keys]


def judge(answer: str, question: dict) -> float | None:
    """自動判定する。判断できない場合は None を返し、手動確認に回す。"""
    said_no_answer = any(p in answer for p in NO_ANSWER_PATTERNS)

    if question["type"] == "none":
        # 判定が逆。「記載がない」と言えたら 1
        return 1.0 if said_no_answer else 0.0

    if said_no_answer:
        return 0.0  # 答えがあるのに答えられなかった

    keys = extract_keys(question["expected"])
    if not keys:
        return None  # 数値がない問題は自動判定できない

    normalized = answer.replace(",", "")
    hit = sum(1 for k in keys if k in normalized)
    if hit == len(keys):
        return 1.0
    if hit > 0:
        return 0.5
    return 0.0


def run_variant(variant: Variant, questions: list[dict], documents: dict[str, str], api_key: str) -> dict:
    """1構成で30問を実行する。"""
    print(f"\n=== {variant.name} : {variant.changed} ===")
    index, model = build_index(variant, documents)
    print(f"  チャンク数: {len(index.chunks)}")

    answers = []
    for i, q in enumerate(questions, 1):
        chunks = index.search(q["question"], model, variant)
        prompt = build_prompt(q["question"], chunks)
        text = ask_gemini(prompt, api_key)
        score = judge(text, q)

        answers.append(
            {
                "id": q["id"],
                "type": q["type"],
                "retrieved": sorted({c.doc_name for c in chunks}),
                "answer": text.replace("\n", " ")[:300],
                "score": score,
                "auto": True,
            }
        )
        mark = "?" if score is None else f"{score:g}"
        print(f"  [{i:02d}] {q['id']:<4} {mark}")
        time.sleep(0.5)  # 無料枠のレート制限に配慮

    return {
        "method": f"custom_{variant.name}",
        "variant": {"changed": variant.changed, "chunk_size": variant.chunk_size,
                    "overlap": variant.overlap, "search": variant.search,
                    "embed_model": variant.embed_model, "top_k": variant.top_k},
        "chunks": len(index.chunks),
        "answers": answers,
    }


def main() -> None:
    """指定された構成を実行する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="baseline", help="実行する構成名。all で全構成")
    args = parser.parse_args()

    api_key = load_api_key()
    questions = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))["questions"]

    documents, unreadable = load_documents()
    print(f"文書 {len(documents)} 件を読み込み。抽出できなかったファイル: {len(unreadable)} 件")
    for name in unreadable:
        print(f"  - {name}（画像PDF。OCR を入れていないため検索対象外）")

    targets = VARIANTS if args.variant == "all" else [v for v in VARIANTS if v.name == args.variant]
    if not targets:
        raise SystemExit(f"構成が見つかりません: {args.variant}")

    RESULTS_DIR.mkdir(exist_ok=True)
    for variant in targets:
        result = run_variant(variant, questions, documents, api_key)
        path = RESULTS_DIR / f"{variant.name}.yaml"
        path.write_text(yaml.dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")

        scored = [a["score"] for a in result["answers"] if a["score"] is not None]
        unknown = sum(1 for a in result["answers"] if a["score"] is None)
        print(f"  → 自動判定 {sum(scored):.1f}/{len(scored)}（判定不能 {unknown} 問） {path}")


if __name__ == "__main__":
    main()

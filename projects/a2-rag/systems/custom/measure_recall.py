"""チャンク戦略・検索方式の効き幅を検索 Recall で測る。

【なぜ生成を挟まないか】
構成を変えて変わるのは「検索で何を拾うか」だけで、
拾った文書から答えを作る部分は全構成で共通。
生成を挟むと LLM の揺らぎが混ざり、**チャンクの効果とノイズを切り分けられない。**

ベースラインの実測で「拾えた文書からは正しく答えている」ことは確認済み
（失点2問はどちらも画像PDFが検索対象外だったことが原因で、検索の問題ではない）。

副次的な利点として、API 呼び出しがゼロになり、数分で全構成を測れる。
"""

import argparse
from pathlib import Path

import yaml

from config import EVAL_DIR, LONG_CORPUS_DIR, VARIANTS
from rag import build_index, load_documents


def doc_id_of(filename: str) -> str:
    """ファイル名から文書ID（REG-001-2025 など）を取り出す。"""
    return filename.split("_", 1)[0]


def measure(variant, questions: list[dict], documents: dict[str, str], corpus_tag: str) -> dict:
    """1構成の Recall を測る。

    type: none の問題は正解文書が存在しないため対象外。
    """
    index, model = build_index(variant, documents, corpus_tag)

    hits = 0
    total = 0
    misses: list[str] = []

    for q in questions:
        sources = q.get("sources") or []
        if not sources:
            continue  # type: none

        retrieved = {doc_id_of(c.doc_name) for c in index.search(q["question"], model, variant)}
        # 根拠文書が複数ある問題は、**すべて拾えて初めて正解**とする。
        # 1つでも欠ければ、その問いには答えられない（横断問題の意味がなくなる）。
        if set(sources) <= retrieved:
            hits += 1
        else:
            misses.append(f"{q['id']}({','.join(sorted(set(sources) - retrieved))})")
        total += 1

    return {
        "name": variant.name,
        "changed": variant.changed,
        "chunks": len(index.chunks),
        "recall": hits / total,
        "hits": hits,
        "total": total,
        "misses": misses,
    }


def main() -> None:
    """全構成の Recall を測って比較表を出す。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--long", action="store_true", help="長文コーパスで測る")
    args = parser.parse_args()
    corpus_tag = "long" if args.long else "short"

    questions = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))["questions"]
    documents, unreadable = load_documents(LONG_CORPUS_DIR if args.long else None)
    avg = sum(len(t) for t in documents.values()) // len(documents)
    print(f"コーパス: {corpus_tag}（{len(documents)} 件・平均 {avg} 字／画像PDF {len(unreadable)} 件は検索対象外）\n")

    results = [measure(v, questions, documents, corpus_tag) for v in VARIANTS]

    print(f"{'構成':<12}{'チャンク':>8}{'Recall':>10}   変更点")
    print("-" * 78)
    baseline = results[0]["recall"]
    for r in results:
        diff = r["recall"] - baseline
        mark = "" if r["name"] == "baseline" else f"  ({diff:+.1%})"
        print(f"{r['name']:<12}{r['chunks']:>8}{r['recall']:>9.1%}{mark:<10} {r['changed']}")

    print("\n=== 拾えなかった問題（括弧内は取りこぼした文書） ===")
    for r in results:
        print(f"  {r['name']:<12} {' '.join(r['misses']) if r['misses'] else '（なし）'}")

    Path(f"results/recall_{corpus_tag}.yaml").write_text(
        yaml.dump(results, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"\n→ results/recall_{corpus_tag}.yaml")


if __name__ == "__main__":
    main()

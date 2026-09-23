"""評価結果を集計する。

主指標は正答率だが、**副指標のハルシネーション率を必ず併記する。**
RAG が嫌われる最大の原因は「それらしい嘘を返すこと」であり、
総合点が同じなら、こちらが低い方式を優先するため。
"""

from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).parent


def load_questions() -> dict[str, dict]:
    """問題を id 引きできる形で読み込む。"""
    data = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    return {q["id"]: q for q in data["questions"]}


def summarize(path: Path, questions: dict[str, dict]) -> dict | None:
    """1方式分の結果を集計する。未記入なら None を返す。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    answers = [a for a in data.get("answers", []) if a.get("score") is not None]
    if not answers:
        return None

    by_type: dict[str, list[float]] = {}
    hallucinated = 0
    for a in answers:
        q = questions[a["id"]]
        by_type.setdefault(q["type"], []).append(float(a["score"]))
        # none 型で満点でない ＝ 記載がないのに答えを作った
        if q["type"] == "none" and float(a["score"]) < 1:
            hallucinated += 1

    none_count = len(by_type.get("none", []))
    return {
        "method": data["method"],
        "total": sum(sum(v) for v in by_type.values()),
        "answered": len(answers),
        "by_type": {t: (sum(v), len(v)) for t, v in by_type.items()},
        "hallucination_rate": hallucinated / none_count if none_count else None,
        "hallucinated": hallucinated,
        "none_count": none_count,
    }


def main() -> None:
    """全方式の結果を比較表として出力する。"""
    questions = load_questions()
    labels = {
        "single": "単一文書",
        "cross": "複数横断",
        "table": "表・数値",
        "none": "記載なし",
    }

    results = []
    for path in sorted((EVAL_DIR / "results").glob("*.yaml")):
        summary = summarize(path, questions)
        if summary:
            results.append(summary)

    if not results:
        print("記入済みの結果がありません。")
        return

    columns = ["方式", "総合", *labels.values(), "ハルシ率"]
    print("  ".join(c.ljust(10) for c in columns))
    print("-" * 84)

    for r in results:
        cells = [r["method"], f"{r['total']:.1f}/{r['answered']}"]
        for t in labels:
            got, n = r["by_type"].get(t, (0, 0))
            cells.append(f"{got:.1f}/{n}" if n else "-")
        rate = r["hallucination_rate"]
        if rate is None:
            cells.append("-")
        else:
            cells.append(f"{rate:.0%} ({r['hallucinated']}/{r['none_count']})")
        print("  ".join(c.ljust(10) for c in cells))

    print()
    print("ハルシ率 = 記載がない問いに、それらしい答えを作ってしまった割合。低いほど良い。")


if __name__ == "__main__":
    main()

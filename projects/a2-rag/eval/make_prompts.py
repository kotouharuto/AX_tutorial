"""評価の投入用リストと、回答記録用の雛形を生成する。

【なぜ questions.yaml をそのまま投げてはいけないか】
expected（正解）と sources（根拠文書ID）が書かれているため、
渡した時点で評価にならない。**質問文だけを抽出する。**

【なぜ順序を混ぜるか】
questions.yaml は type 順に並んでおり、type: none（答えが存在しない）が
最後に5問連続する。この順で投げると、チャット履歴に引きずられて
「ありません」を連発する／逆に前半の流れででっち上げる、という
質問内容と無関係な偏りが出る。

**ただしシードを固定し、全方式で同じ順にする。** 順序が違えば比較にならない。
"""

import random
from pathlib import Path

import yaml

SEED = 20260901  # corpus と同じシード。全方式でこの順序を使う。
EVAL_DIR = Path(__file__).parent
QUESTIONS = EVAL_DIR / "questions.yaml"
PROMPTS_OUT = EVAL_DIR / "prompts.txt"
RESULTS_DIR = EVAL_DIR / "results"

# 全方式で同じ前置きを使う。方式ごとに変えると条件が揃わない。
SYSTEM_NOTE = """以下は社内文書についての質問です。
アップロードされた文書のみを根拠に答えてください。
文書に記載がない場合は、推測せず「文書に記載がありません」と答えてください。
"""


def load_questions() -> list[dict]:
    """評価問題を読み込む。"""
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if not data["meta"].get("frozen"):
        raise RuntimeError("questions.yaml が frozen ではありません。構築開始後の変更は比較を壊します。")
    return data["questions"]


def shuffled(questions: list[dict]) -> list[dict]:
    """固定シードで順序を混ぜ、type: none が隣り合わないように整える。

    none が連続すると「記載がありません」を続けて答える流れができ、
    次の問題の判断が質問内容ではなく直前の回答に引きずられる。

    **シードを変えて都合の良い並びを探すのではなく、決定的な後処理で直す。**
    シード探しは「条件に合う結果が出るまで試す」ことになり、恣意的になる。
    """
    rng = random.Random(SEED)
    order = list(questions)
    rng.shuffle(order)

    # none が連続する箇所を、後方の none でない問題と入れ替える。
    # 前から順に走査し、最初に見つかった交換候補を使う（決定的）。
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


def write_prompts(order: list[dict]) -> None:
    """投入用のテキストを書き出す。質問文以外は一切含めない。"""
    lines = [
        "# 評価用プロンプト（この順で1問ずつ投げる）",
        "#",
        "# 【注意】正解・根拠文書は含まれていない。questions.yaml を直接渡さないこと。",
        "# 【注意】1問ずつ投げる。まとめて投げると1問あたりの回答が短くなり、",
        "#         実際の利用条件から外れる。",
        "",
        "## 各問の前に付ける前置き（全方式共通）",
        "",
        SYSTEM_NOTE,
        "-" * 60,
        "",
    ]
    for i, q in enumerate(order, 1):
        lines.append(f"[{i:02d}] {q['id']}")
        lines.append(q["question"])
        lines.append("")

    PROMPTS_OUT.write_text("\n".join(lines), encoding="utf-8")


def write_result_template(order: list[dict], method: str) -> Path:
    """回答記録用の雛形を書き出す。

    回答は全文ではなく**要点のみ**記録する。
    全文を残すと転記の手間が大きく、採点の障害になる。
    判定に迷った回答だけ note に残せばよい。
    """
    path = RESULTS_DIR / f"{method}.yaml"
    if path.exists():
        return path  # 既存の記録を上書きしない

    lines = [
        f"method: {method}",
        "date: ",
        "note: |",
        "  構築にかかった時間、詰まった点などをここに書く",
        "",
        "# score: 1 / 0.5 / 0",
        "#   type が none の問題は判定が逆。「記載がない」と言えたら 1、でっち上げたら 0。",
        "answers:",
    ]
    for i, q in enumerate(order, 1):
        lines.append(f"  - id: {q['id']}          # [{i:02d}] type={q['type']}")
        lines.append('    answer: ""')
        lines.append("    score: ")
        lines.append('    note: ""')
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    """投入用リストと記録雛形を生成する。"""
    RESULTS_DIR.mkdir(exist_ok=True)
    order = shuffled(load_questions())

    write_prompts(order)
    created = [write_result_template(order, m) for m in ("notebooklm", "claude_projects", "dify", "custom")]

    print(f"投入用: {PROMPTS_OUT}")
    print("記録用:")
    for path in created:
        print(f"  {path}")
    print()
    print("順序（先頭10問）:")
    for i, q in enumerate(order[:10], 1):
        print(f"  [{i:02d}] {q['id']} ({q['type']})")
    none_positions = [i for i, q in enumerate(order, 1) if q["type"] == "none"]
    print(f"\ntype=none の出現位置: {none_positions}（連続していなければ良い）")


if __name__ == "__main__":
    main()

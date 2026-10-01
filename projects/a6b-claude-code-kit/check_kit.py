"""キットの静的な整合性チェック。

**再現テストではない。** 手順書が参照するファイルが実在するか、
記述と実体が一致するかだけを見る。

【なぜ再現テストをここでやらないか】到達条件「手順書だけを見て30分以内に再現できる」は
**人が手順書だけを見て実行しないと検証にならない。**
Claude Code が実行すると、手順書の抜けを文脈から補って成功してしまう。
このスクリプトは「手順書とファイルがずれていないか」だけを担う。
"""

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 手順書（SETUP.md）が配置を指示しているファイル。
# ここと kit/ の実体がずれたら、手順どおりにやっても足りない／余る。
REFERENCED = (
    "kit/.claude/settings.json",
    "kit/.claude/skills/commit-check/SKILL.md",
    "kit/.claude/skills/explain-change/SKILL.md",
    "kit/CLAUDE.md",
    "kit/.mcp.json",
)

# 秘密情報らしい文字列の検出パターン。
SECRET_PATTERN = re.compile(
    r"ctx7sk[A-Za-z0-9_-]{8,}"
    r"|sk-[A-Za-z0-9]{16,}"
    r"|ghp_[A-Za-z0-9]{16,}"
    r"|AKIA[A-Z0-9]{12,}"
    r"|Bearer\s+[A-Za-z0-9._-]{16,}"
    r"|://[A-Za-z0-9._-]+:[A-Za-z0-9._%-]{6,}@"
)

# 検出パターンそのものを**文書として列挙している**ファイル。
# 除外しないと、秘密情報の検出を説明したファイルが毎回引っかかる。
# 【注意】除外は「このファイルは見ない」ではなく「この理由で除外した」と書くこと。
SECRET_SCAN_EXCLUDE = {
    # コミット前に探すべき文字列の形を例示しているため
    "kit/.claude/skills/commit-check/SKILL.md",
    # 本ファイル自身が検出パターンを持つため
    "check_kit.py",
}


def main() -> int:
    """チェックを実行する。問題があれば終了コード 1。"""
    problems: list[str] = []
    checks: list[str] = []

    # 1) 手順書が参照するファイルが実在するか
    for rel in REFERENCED:
        if (BASE_DIR / rel).is_file():
            checks.append(f"存在 OK  {rel}")
        else:
            problems.append(f"手順書が参照するファイルが無い: {rel}")

    # 2) kit/ にあるのに手順書が配置を指示していないファイルはないか。
    #    余っているファイルは「配置されないまま放置される」ので問題として扱う。
    actual = {
        str(p.relative_to(BASE_DIR)) for p in (BASE_DIR / "kit").rglob("*") if p.is_file()
    }
    for rel in sorted(actual - set(REFERENCED)):
        problems.append(f"kit にあるが手順書が配置を指示していない: {rel}")

    # 3) JSON が妥当か
    for rel in ("kit/.claude/settings.json", "kit/.mcp.json"):
        try:
            json.loads((BASE_DIR / rel).read_text(encoding="utf-8"))
            checks.append(f"JSON OK  {rel}")
        except json.JSONDecodeError as exc:
            problems.append(f"JSON が壊れている {rel}: {exc.msg}")

    settings = json.loads((BASE_DIR / "kit/.claude/settings.json").read_text(encoding="utf-8"))
    perm = settings["permissions"]

    # 4) README に書いた件数が実体と一致するか（記述と実体のずれを防ぐ）
    actual_counts = {k: len(perm.get(k, [])) for k in ("allow", "ask", "deny")}
    readme = (BASE_DIR / "README.md").read_text(encoding="utf-8")
    match = re.search(r"allow (\d+) / ask (\d+) / deny (\d+)", readme)
    if match is None:
        problems.append("README に権限の件数の記載が見つからない")
    else:
        stated = dict(zip(("allow", "ask", "deny"), (int(g) for g in match.groups())))
        if stated == actual_counts:
            checks.append(f"件数 OK  {actual_counts}")
        else:
            problems.append(f"README の件数が実体と違う: 記載 {stated} / 実体 {actual_counts}")

    # 5) defaultMode が入っていないこと。
    #    公式仕様でプロジェクト設定からは auto / bypassPermissions が効かないため、
    #    書くと「設定したのに反映されない」で時間を溶かす。
    if "defaultMode" in perm:
        problems.append("共有設定に permissions.defaultMode がある（プロジェクト設定では効かない）")
    else:
        checks.append("defaultMode なし OK（意図どおり）")

    # 6) 秘密情報が混ざっていないこと
    scanned = 0
    for path in sorted(BASE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(BASE_DIR))
        if rel in SECRET_SCAN_EXCLUDE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # バイナリは対象外
        scanned += 1
        if SECRET_PATTERN.search(text):
            problems.append(f"秘密情報らしい文字列を含む: {rel}")
    checks.append(f"秘密情報の走査 OK  {scanned} ファイル（除外 {len(SECRET_SCAN_EXCLUDE)} 件）")

    # 7) スキルの frontmatter に description があるか（無いと候補に出ない）
    for rel in sorted(r for r in actual if r.endswith("SKILL.md")):
        text = (BASE_DIR / rel).read_text(encoding="utf-8")
        frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if frontmatter is None:
            problems.append(f"frontmatter が無い: {rel}")
        elif "description:" not in frontmatter.group(1):
            problems.append(f"description が無い: {rel}")
        else:
            checks.append(f"frontmatter OK  {rel}")

    # 8) 雛形に未記入の <> が残っていること（残っているのが正しい）
    if "<" in (BASE_DIR / "kit/CLAUDE.md").read_text(encoding="utf-8"):
        checks.append("雛形に <> が残っている OK（埋めるのは利用者）")
    else:
        problems.append("雛形の <> が無い（雛形として機能しない）")

    print("=== 確認した項目 ===")
    for line in checks:
        print(f"  {line}")
    print("\n=== 問題 ===")
    if problems:
        for line in problems:
            print(f"  ★ {line}")
    else:
        print("  なし")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

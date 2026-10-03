"""本番コードが標準出力に書かないことを静的に検査する。

【なぜ静的に見るか】観察の結果、SDK v2.3.0 では素朴な print() が呼び出しを壊さなかった
（サーバが stdout を退避し、Python クライアントが不正な行を捨てる）。
**壊れないので、入っても気づけない。** しかし起動時やバッファ経由では実際に
通信路へ不正な行が流れており、別実装のクライアント（Claude Code・Desktop）が
同じように寛容とは限らない。動作確認では見つからないので、コードで止める。
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _stdout_writes(path: Path) -> list[str]:
    """print() と sys.stdout への書き込みを探す。"""
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # print(...)。file= で stderr を明示していれば許す
        if isinstance(func, ast.Name) and func.id == "print":
            targets = [kw for kw in node.keywords if kw.arg == "file"]
            if not targets or "stdout" in ast.unparse(targets[0].value):
                found.append(f"{path.name}:{node.lineno} print()")
        # sys.stdout.write(...) / sys.stdout.buffer.write(...)
        if isinstance(func, ast.Attribute) and func.attr == "write":
            if "sys.stdout" in ast.unparse(func.value):
                found.append(f"{path.name}:{node.lineno} {ast.unparse(func)}()")
    return found


def test_本番コードが標準出力に書かない() -> None:
    offenders = [hit for path in sorted(SRC.glob("*.py")) for hit in _stdout_writes(path)]
    assert not offenders, "stdio サーバで標準出力に書いている: " + ", ".join(offenders)


def test_検査自体がprintを検出できる(tmp_path: Path) -> None:
    """検査が空振りしていないことを確かめる（検査の検査）。"""
    bad = tmp_path / "bad.py"
    bad.write_text('import sys\nprint("x")\nsys.stdout.write("y")\n', encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text('import sys\nprint("x", file=sys.stderr)\n', encoding="utf-8")
    assert len(_stdout_writes(bad)) == 2
    assert _stdout_writes(good) == []

"""検索の単体テスト（プロセス内）。

stdio のテスト（test_stdio.py）はプロトコル越しの挙動を確かめるが、
別プロセスなのでカバレッジが追えない。ここでは同じ処理を直接呼ぶ。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server as server_mod  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from search import CorpusError, Index, load_corpus, split_chunks, tokenize_ja  # noqa: E402


# 【文書数を5件にしている理由】BM25（Okapi）の idf は「半数の文書に出る語」で 0 になる。
# 2文書だと、該当する文書があってもスコアが 0 になり「該当なし」になる（既知の制約・下で固定）。
DOCS = {
    "経費精算": "# 経費精算\n\n申請期限は翌月5日まで。\n\n領収書の原本を添付する。",
    "備品": "# 備品購入\n\n1万円未満は所属長承認のみ。",
    "休暇": "# 休暇の申請\n\n有給休暇は前日までに申請する。",
    "出張": "# 出張の手続き\n\n出張旅費は規程の上限まで支給する。",
    "社用車": "# 社用車の利用\n\n予約は総務部のシステムで行う。",
}


def make_corpus(tmp_path: Path, docs: dict[str, str] | None = None) -> Path:
    for name, text in (docs or DOCS).items():
        (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    (tmp_path / "画像.pdf").write_bytes(b"%PDF-1.4")  # 対象外
    (tmp_path / "サブ").mkdir()  # フォルダは読まない
    return tmp_path


# --- search.py ---------------------------------------------------------------


def test_bigramに分割する() -> None:
    assert tokenize_ja("経費 精算") == ["経費", "費精", "精算"]
    assert tokenize_ja("あ") == []


def test_段落単位でまとめ大きさで区切る() -> None:
    text = "\n\n".join(["あ" * 150] * 4)
    chunks = split_chunks("doc", text, size=400)
    assert len(chunks) == 2
    assert [c.index for c in chunks] == [0, 1]
    assert all(c.doc_name == "doc" for c in chunks)


def test_空の段落は無視する() -> None:
    assert split_chunks("doc", "\n\n   \n\n") == []


def test_対象外のファイルは捨てずに返す(tmp_path: Path) -> None:
    chunks, skipped = load_corpus(make_corpus(tmp_path))
    assert skipped == ["画像.pdf"]
    assert {c.doc_name for c in chunks} == set(DOCS)


@pytest.mark.parametrize(
    ("setup", "message"),
    [("none", "存在しない"), ("file", "フォルダではない"), ("empty", "1件もない")],
)
def test_コーパスを読めない原因を区別する(tmp_path: Path, setup: str, message: str) -> None:
    target = {"none": tmp_path / "none", "file": tmp_path / "a.md", "empty": tmp_path}[setup]
    if setup == "file":
        target.write_text("x", encoding="utf-8")
    with pytest.raises(CorpusError, match=message):
        load_corpus(target)


def test_関連する文書が上位に来る(tmp_path: Path) -> None:
    chunks, _ = load_corpus(make_corpus(tmp_path))
    hits = Index(chunks).search("経費精算の申請期限", top_k=2)
    assert hits[0].doc_name == "経費精算"


def test_既知の制約_文書が2件だと該当があっても0件になる(tmp_path: Path) -> None:
    """**静かに誤る。** 該当する文書があるのに「該当なし」を返し、Claude は「記載が無い」と答える。

    BM25（Okapi）の idf は log((N - n + 0.5) / (n + 0.5))。N=2・n=1 で log(1) = 0 になる。
    方式は変えない（検索精度のチューニングは A-6a の目的外）。
    文書が数件しかないなら、検索せず全文を渡せばよい。
    この挙動が変わったら（ライブラリ更新など）、このテストで気づけるようにしておく。
    """
    two_docs = {k: DOCS[k] for k in ("経費精算", "備品")}
    chunks, _ = load_corpus(make_corpus(tmp_path, two_docs))
    assert Index(chunks).search("経費精算", top_k=5) == []


def test_スコア0の文書は返さない(tmp_path: Path) -> None:
    chunks, _ = load_corpus(make_corpus(tmp_path))
    assert Index(chunks).search("zzzz", top_k=5) == []


def test_空の検索語は空を返す(tmp_path: Path) -> None:
    chunks, _ = load_corpus(make_corpus(tmp_path))
    assert Index(chunks).search(" ", top_k=5) == []


# --- server.py の search_documents（プロセス内） ---------------------------------


@pytest.fixture(autouse=True)
def reset_index() -> None:
    """インデックスはモジュール内で保持されるので、テストごとに作り直す。"""
    server_mod._index = None


async def call(args: dict) -> str:
    result = await server_mod.server.call_tool("search_documents", args)
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


async def test_出典付きで返す(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A6A_CORPUS_DIR", str(make_corpus(tmp_path)))
    text = await call({"query": "経費精算", "top_k": 1})
    assert "出典：経費精算" in text


async def test_該当なしは推測を禁じる(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A6A_CORPUS_DIR", str(make_corpus(tmp_path)))
    text = await call({"query": "zzzz"})
    assert "推測で回答しないこと" in text


async def test_インデックスは2回目以降に再利用する(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A6A_CORPUS_DIR", str(make_corpus(tmp_path)))
    await call({"query": "経費"})
    first = server_mod._index
    await call({"query": "備品"})
    assert server_mod._index is first


async def test_未設定は原因が届く(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A6A_CORPUS_DIR", raising=False)
    with pytest.raises(ToolError, match="A6A_CORPUS_DIR"):
        await call({"query": "経費"})


async def test_読めないフォルダは原因が届く(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A6A_CORPUS_DIR", str(tmp_path / "none"))
    with pytest.raises(ToolError, match="存在しない"):
        await call({"query": "経費"})

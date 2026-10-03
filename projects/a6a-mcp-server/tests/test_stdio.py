"""stdio で実際にサーバを起動し、クライアントとして接続するテスト。

**サーバ側の call_tool() だけでは、プロトコル越しに Claude が何を受け取るかは分からない。**
ここでは別プロセスとして起動し、JSON-RPC 越しに結果を確かめる。

【環境変数の注意】SDK の stdio クライアントは、親の環境変数を
HOME・LOGNAME・PATH・SHELL・TERM・USER の6つしか子プロセスに渡さない。
シェルで export しただけの変数はサーバから見えないので、`env` に明示する。
"""

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

PROJECT_DIR = Path(__file__).resolve().parent.parent
SERVER = PROJECT_DIR / "src" / "server.py"
# A-2 のコーパス。テストでは実在のパスを使う（import はしない。データを読むだけ）
CORPUS_DIR = PROJECT_DIR.parent / "a2-rag" / "corpus" / "out"


def params(extra_env: dict[str, str] | None = None) -> StdioServerParameters:
    """サーバの起動設定。環境変数は明示的に渡す。"""
    env = get_default_environment()
    env.update(extra_env or {})
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


def text_of(result: object) -> str:
    """ツール結果の本文を連結する。"""
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


async def call(tool: str, args: dict, extra_env: dict[str, str] | None = None):
    """サーバを起動してツールを1回呼ぶ。"""
    async with stdio_client(params(extra_env)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool, args)


@pytest.mark.skipif(not CORPUS_DIR.is_dir(), reason="A-2 のコーパスが無い環境")
async def test_ツール一覧に検索が出る() -> None:
    async with stdio_client(params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
    names = [t.name for t in tools.tools]
    assert "search_documents" in names


@pytest.mark.skipif(not CORPUS_DIR.is_dir(), reason="A-2 のコーパスが無い環境")
async def test_検索すると出典付きで返る() -> None:
    result = await call(
        "search_documents", {"query": "経費精算", "top_k": 3}, {"A6A_CORPUS_DIR": str(CORPUS_DIR)}
    )
    body = text_of(result)
    assert not result.is_error
    assert "出典：" in body


async def test_コーパス未設定ならClaudeに原因が届く() -> None:
    """**到達条件の核心。** 原因が隠されず、設定すべき環境変数名まで届くこと。"""
    result = await call("search_documents", {"query": "経費精算"})
    body = text_of(result)
    assert result.is_error
    assert "A6A_CORPUS_DIR" in body, f"原因が届いていない: {body!r}"
    # 接頭辞 "Error executing tool <名前>" は ToolError でも付く。
    # クラッシュ扱いとの違いは「コロンの後ろに原因が続くか」。
    assert body != "Error executing tool search_documents", "想定外のクラッシュ扱いになっている"


async def test_存在しないフォルダなら原因が届く(tmp_path: Path) -> None:
    result = await call(
        "search_documents", {"query": "経費"}, {"A6A_CORPUS_DIR": str(tmp_path / "none")}
    )
    assert result.is_error
    assert "存在しない" in text_of(result)


async def test_空のフォルダなら0件ではなく異常として返る(tmp_path: Path) -> None:
    """**検索結果なし（正常）と、文書が1件もない（設定ミス）を区別する。**"""
    result = await call("search_documents", {"query": "経費"}, {"A6A_CORPUS_DIR": str(tmp_path)})
    assert result.is_error
    assert "1件もない" in text_of(result)


@pytest.mark.skipif(not CORPUS_DIR.is_dir(), reason="A-2 のコーパスが無い環境")
async def test_該当なしは異常ではないが推測を禁じる() -> None:
    result = await call(
        "search_documents", {"query": "量子コンピュータの冷却装置"},
        {"A6A_CORPUS_DIR": str(CORPUS_DIR)},
    )
    # bi-gram なので完全な0件にならない可能性がある。どちらでも推測を禁じる文言を確認する
    body = text_of(result)
    assert not result.is_error
    if "見つからなかった" in body:
        assert "推測で回答しないこと" in body


@pytest.mark.parametrize(
    ("args", "expected"),
    [({"query": "   "}, "空"), ({"query": "経費", "top_k": 0}, "1〜10"),
     ({"query": "経費", "top_k": 99}, "1〜10")],
)
async def test_入力の誤りは理由付きで返る(args: dict, expected: str) -> None:
    result = await call("search_documents", args, {"A6A_CORPUS_DIR": str(CORPUS_DIR)})
    assert result.is_error
    assert expected in text_of(result)


async def test_親の環境変数はそのままでは子に渡らない(monkeypatch: pytest.MonkeyPatch) -> None:
    """**export しただけではサーバから見えない**ことを固定する。"""
    monkeypatch.setenv("A6A_CORPUS_DIR", str(CORPUS_DIR))
    assert os.environ["A6A_CORPUS_DIR"]  # 親には設定されている
    result = await call("search_documents", {"query": "経費精算"})  # env に渡さない
    assert result.is_error, "親の環境変数が漏れて渡っている（SDK の挙動が変わった）"
    assert "設定されていない" in text_of(result)


# --- SDK v2 の例外の扱いをプロトコル越しに固定する -------------------------------

PROBE = Path(__file__).resolve().parent / "probe_server.py"


async def call_probe(tool: str):
    server = StdioServerParameters(
        command=sys.executable, args=[str(PROBE)], env=get_default_environment()
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool, {})


async def test_ToolErrorなら原因がClaudeに届く() -> None:
    result = await call_probe("raise_tool_error")
    assert result.is_error
    assert "A6A_CORPUS_DIR" in text_of(result)


async def test_ValueErrorだと原因が隠される() -> None:
    """**v1 の感覚で普通の例外を投げると、原因が Claude に届かない。**
    利用者は「失敗した」としか聞けず、何を直せばよいか分からない。"""
    result = await call_probe("raise_value_error")
    body = text_of(result)
    assert result.is_error
    assert body == "Error executing tool raise_value_error", f"想定と違う: {body!r}"
    assert "A6A_CORPUS_DIR" not in body, "原因が漏れている（SDK の挙動が変わった）"

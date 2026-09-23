"""自作RAGの設定。

【測定範囲を先に決める】
効き幅の測定は際限なくできる。全組み合わせ（チャンク3 × オーバーラップ2 ×
検索方式2 × 埋め込み2 = 24構成）は測らない。

**一度に1要素だけ変える。** 複数変えると何が効いたか分からなくなる
（A-1 のリトライ検証と同じ原則）。ベースライン＋6変種の7構成で止める。
"""

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = PROJECT_ROOT / "a2-rag" / "corpus" / "out"
# 長文版。短文コーパスでは1文書＝1チャンクになり、チャンク戦略の効き幅が測れなかったため、
# 形式的な条文を足して実務並みの長さにしたもの（元の本文は変更していない）。
LONG_CORPUS_DIR = PROJECT_ROOT / "a2-rag" / "corpus" / "out_long"
EVAL_DIR = PROJECT_ROOT / "a2-rag" / "eval"
CACHE_DIR = Path(__file__).parent / "cache"

# Gemini API（A-1 と同じ無料枠を使う。架空文書なので学習に使われても問題ない）
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


@dataclass(frozen=True)
class Variant:
    """測定する1構成。

    name 以外は1つだけがベースラインと異なる。
    """

    name: str
    chunk_size: int = 512
    overlap: int = 50
    search: str = "vector"  # vector | hybrid
    embed_model: str = "intfloat/multilingual-e5-small"
    top_k: int = 5
    changed: str = "（ベースライン）"


VARIANTS: list[Variant] = [
    Variant(name="baseline"),
    Variant(name="chunk256", chunk_size=256, changed="チャンクサイズ 512→256"),
    Variant(name="chunk1024", chunk_size=1024, changed="チャンクサイズ 512→1024"),
    Variant(name="overlap0", overlap=0, changed="オーバーラップ 50→0"),
    Variant(name="hybrid", search="hybrid", changed="検索方式 ベクトル→ハイブリッド(BM25併用)"),
    Variant(name="topk10", top_k=10, changed="取得件数 5→10"),
    Variant(name="e5base", embed_model="intfloat/multilingual-e5-base",
            changed="埋め込みモデル e5-small→e5-base"),
]

# E5 系のモデルは接頭辞が必須。付けないと精度が明確に落ちる。
# 「実装を知らないと踏む」タイプの落とし穴なので、定数として明示しておく。
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "

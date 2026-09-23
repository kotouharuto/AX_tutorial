"""自作RAG：取り込み・チャンク分割・検索。

【LlamaIndex 等を使わない理由】
目的はチャンク戦略と検索方式の効き幅を測ること。
フレームワークの抽象化を挟むと、何が効いたのかを追いにくい。
60文書・数百チャンクの規模ならベクトルDBも不要で numpy で足りる。
依存が少ない方が他人の環境でも動く（A-1 の教訓）。
"""

import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from config import CACHE_DIR, CORPUS_DIR, E5_PASSAGE_PREFIX, E5_QUERY_PREFIX, Variant


@dataclass
class Chunk:
    """検索単位。どの文書から来たかを必ず保持する（出典を示すため）。"""

    doc_name: str
    text: str


def load_documents(corpus_dir: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """コーパスを読み込む。

    **画像PDFはテキスト抽出できないので、ここで落ちる。**
    OCR は入れない。「テキスト抽出しかできない」ことが自作構成の制約であり、
    既製方式（NotebookLM / Claude Projects）との差がここに出ることを実証するため。

    @returns 読み込めた文書と、読み込めなかったファイル名
    """
    documents: dict[str, str] = {}
    unreadable: list[str] = []

    for path in sorted((corpus_dir or CORPUS_DIR).iterdir()):
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
        elif path.suffix == ".pdf":
            text = "".join(page.extract_text() or "" for page in PdfReader(path).pages)
        else:
            continue

        if text.strip():
            documents[path.name] = text
        else:
            # 抽出0文字。画像PDF。検索対象にすら入らない。
            unreadable.append(path.name)

    return documents, unreadable


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """文字数ベースで分割する。

    日本語なので単語境界での分割は形態素解析が要る。
    ここでは改行を優先境界とした素朴な文字数分割にする。
    **素朴さ自体が測定対象**（チャンク戦略の効き幅を見るため）。
    """
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # 境界が文の途中に来ないよう、後方の改行まで戻す（戻しすぎない範囲で）
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary != -1:
                end = boundary
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return [c for c in chunks if c]


def build_chunks(documents: dict[str, str], variant: Variant) -> list[Chunk]:
    """全文書をチャンクに分割する。"""
    chunks: list[Chunk] = []
    for name, text in documents.items():
        for piece in chunk_text(text, variant.chunk_size, variant.overlap):
            chunks.append(Chunk(doc_name=name, text=piece))
    return chunks


def tokenize_ja(text: str) -> list[str]:
    """BM25 用の日本語トークナイズ。

    形態素解析器を入れると依存が重くなるため、**文字bi-gram**で代用する。
    日本語の語彙検索では定番の手法。表記ゆれ（Wi-Fi / WiFi）には弱い。
    """
    normalized = re.sub(r"\s+", "", text.lower())
    return [normalized[i : i + 2] for i in range(len(normalized) - 1)]


class Index:
    """検索インデックス。ベクトルと BM25 の両方を持つ。"""

    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        self.chunks = chunks
        self.embeddings = embeddings
        self.bm25 = BM25Okapi([tokenize_ja(c.text) for c in chunks])

    def search(self, query: str, model: SentenceTransformer, variant: Variant) -> list[Chunk]:
        """検索する。方式は variant.search で切り替える。"""
        # E5 系は接頭辞が必須。付けないと精度が落ちる。
        query_vec = model.encode([E5_QUERY_PREFIX + query], normalize_embeddings=True)[0]
        vector_scores = self.embeddings @ query_vec  # 正規化済みなので内積＝コサイン類似度

        if variant.search == "vector":
            scores = vector_scores
        elif variant.search == "hybrid":
            bm25_scores = np.array(self.bm25.get_scores(tokenize_ja(query)))
            # スケールが違うので、それぞれ 0〜1 に正規化してから足す。
            # 重みは 0.5:0.5。ここを調整し出すと際限がないので固定する。
            scores = _normalize(vector_scores) * 0.5 + _normalize(bm25_scores) * 0.5
        else:
            raise ValueError(f"未知の検索方式: {variant.search}")

        top = np.argsort(scores)[::-1][: variant.top_k]
        return [self.chunks[i] for i in top]


def _normalize(scores: np.ndarray) -> np.ndarray:
    """0〜1 に正規化する。全て同値なら 0 を返す。"""
    span = scores.max() - scores.min()
    if span == 0:
        return np.zeros_like(scores)
    return (scores - scores.min()) / span


def build_index(
    variant: Variant, documents: dict[str, str], corpus_tag: str = "short"
) -> tuple[Index, SentenceTransformer]:
    """インデックスを構築する。構成ごとにキャッシュする。

    埋め込みの再計算は構成を変えるたびに発生するため、
    キャッシュがないと測定のたびに待たされる。
    """
    CACHE_DIR.mkdir(exist_ok=True)
    # コーパスもキャッシュキーに含める。含めないと短文版と長文版の埋め込みが混ざる。
    key = f"{corpus_tag}_{variant.embed_model.replace('/', '_')}_{variant.chunk_size}_{variant.overlap}"
    cache_path = CACHE_DIR / f"{key}.pkl"

    model = SentenceTransformer(variant.embed_model)

    if cache_path.exists():
        with cache_path.open("rb") as f:
            chunks, embeddings = pickle.load(f)
    else:
        chunks = build_chunks(documents, variant)
        embeddings = model.encode(
            [E5_PASSAGE_PREFIX + c.text for c in chunks],
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        with cache_path.open("wb") as f:
            pickle.dump((chunks, embeddings), f)

    return Index(chunks, np.asarray(embeddings)), model

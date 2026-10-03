"""社内文書の検索（BM25・文字 bi-gram）。MCP に依存しない純粋な処理として分ける。

【A-2 のコードを import しない理由】各 `projects/*` は独立して動かす規約のため。
同じ方式（文字 bi-gram の BM25）を書き直している。

【埋め込みを使わない理由】stdio の MCP サーバはクライアントが起動のたびに立ち上げる。
torch の読み込みは毎回数秒、初回はエンドポイント保護のスキャンで数分かかりうる。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

# テキストとして読めるものだけを対象にする。
# PDF はテキスト抽出の依存（pypdf）が増え、画像 PDF は抽出できないため対象外。
SUPPORTED_SUFFIXES = (".md", ".txt")
CHUNK_SIZE = 400  # 文字数。A-2 の baseline（512 トークン）に近い粒度


@dataclass(frozen=True)
class Chunk:
    """検索単位。**出典を必ず保持する**（どの文書の何番目か）。"""

    doc_name: str
    index: int
    text: str


@dataclass(frozen=True)
class Hit:
    """検索結果1件。"""

    doc_name: str
    score: float
    text: str


class CorpusError(Exception):
    """コーパスを読めない。**利用者が対処できる原因**を message に入れる。"""


def tokenize_ja(text: str) -> list[str]:
    """文字 bi-gram に分割する。日本語は空白で区切れないため。"""
    normalized = re.sub(r"\s+", "", text.lower())
    return [normalized[i : i + 2] for i in range(len(normalized) - 1)]


def split_chunks(doc_name: str, text: str, size: int = CHUNK_SIZE) -> list[Chunk]:
    """段落単位でまとめ、size を超えたら区切る。"""
    chunks: list[Chunk] = []
    buffer = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if buffer and len(buffer) + len(paragraph) > size:
            chunks.append(Chunk(doc_name, len(chunks), buffer))
            buffer = ""
        buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        chunks.append(Chunk(doc_name, len(chunks), buffer))
    return chunks


def load_corpus(corpus_dir: Path) -> tuple[list[Chunk], list[str]]:
    """コーパスを読む。対象外のファイル名も返す（黙って捨てない）。"""
    if not corpus_dir.exists():
        raise CorpusError(f"文書フォルダが存在しない: {corpus_dir}")
    if not corpus_dir.is_dir():
        raise CorpusError(f"文書フォルダとして指定されたものがフォルダではない: {corpus_dir}")

    chunks: list[Chunk] = []
    skipped: list[str] = []
    for path in sorted(corpus_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        chunks.extend(split_chunks(path.stem, text))

    if not chunks:
        # 0件を「検索結果なし」と区別する。フォルダの指定違いで起きることが多い。
        raise CorpusError(
            f"文書フォルダに検索できる文書が1件もない（対象: {', '.join(SUPPORTED_SUFFIXES)}）: "
            f"{corpus_dir}"
        )
    return chunks, skipped


class Index:
    """BM25 の検索インデックス。"""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize_ja(c.text) for c in chunks])

    def search(self, query: str, top_k: int) -> list[Hit]:
        """上位 top_k 件を返す。スコアが 0 のものは返さない（無関係な文書を混ぜない）。"""
        tokens = tokenize_ja(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            Hit(self.chunks[i].doc_name, float(scores[i]), self.chunks[i].text)
            for i in ranked[:top_k]
            if scores[i] > 0
        ]

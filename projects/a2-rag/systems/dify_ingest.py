"""Dify の Knowledge API で60文書を一括投入する。

【なぜ API を使うか】
UI のアップロードで複数ファイルを選択できず、1件ずつ60回の操作になるため。
UPLOAD_FILE_BATCH_LIMIT を引き上げても解消しなかった。

【評価上の注意】
他の3方式と**同じ60ファイルを同じ形式で**投入する。
Notion 連携などを経由すると PDF の構造が変わり、比較にならない。

【記録すべき点】
API 投入は確実に動くが、「非エンジニアには無理な操作」を1つ追加している。
Dify を「運用を他人に渡せる方式」として評価している最中に、
UI で完結できなかったこと自体が評価結果になる。
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJECT_DIR / "corpus" / "out"
ENV_PATH = PROJECT_DIR / ".env"

BASE_URL = "http://localhost:8080/v1"

# DB の providers テーブルで確認した値。プラグイン方式なのでこの形式になる。
EMBEDDING_PROVIDER = "langgenius/gemini/google"
EMBEDDING_MODEL = "gemini-embedding-001"  # embedding-001 は提供終了（404）


def load_key() -> str:
    """Knowledge API キーを .env から読む。形式を検証してプレースホルダ事故を防ぐ。"""
    if not ENV_PATH.exists():
        raise RuntimeError(f"{ENV_PATH} がありません。")
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("DIFY_KNOWLEDGE_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not key.isascii():
                raise RuntimeError("DIFY_KNOWLEDGE_API_KEY に非 ASCII 文字が含まれています。プレースホルダのままではありませんか。")
            if not key.startswith("dataset-"):
                raise RuntimeError(f"DIFY_KNOWLEDGE_API_KEY は 'dataset-' で始まるはずです（先頭: {key[:8]!r}）。")
            return key
    raise RuntimeError(f"{ENV_PATH} に DIFY_KNOWLEDGE_API_KEY=... を追記してください。")


def api(method: str, path: str, key: str, **kwargs) -> dict:
    """API を呼び、非 2xx は本文付きで明示的に失敗させる。"""
    res = requests.request(method, f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {key}"}, timeout=120, **kwargs)
    if not res.ok:
        raise RuntimeError(f"{method} {path} → {res.status_code}: {res.text[:400]}")
    return res.json() if res.text else {}


def create_dataset(key: str, name: str) -> str:
    """ナレッジを作成し、ID を返す。埋め込みモデルをここで固定する。"""
    body = {
        "name": name,
        "indexing_technique": "high_quality",
        "permission": "only_me",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_model_provider": EMBEDDING_PROVIDER,
    }
    data = api("POST", "/datasets", key, json=body)
    return data["id"]


def upload_file(key: str, dataset_id: str, path: Path) -> str:
    """1ファイルを投入し、document_id を返す。チャンク設定は自動（他方式と条件を揃えるため触らない）。"""
    meta = {
        "indexing_technique": "high_quality",
        "process_rule": {"mode": "automatic"},
        "embedding_model": EMBEDDING_MODEL,
        "embedding_model_provider": EMBEDDING_PROVIDER,
    }
    with path.open("rb") as f:
        data = api(
            "POST",
            f"/datasets/{dataset_id}/document/create-by-file",
            key,
            data={"data": json.dumps(meta, ensure_ascii=False)},
            files={"file": (path.name, f)},
        )
    return data["document"]["id"]


def wait_indexing(key: str, dataset_id: str, expected: int) -> None:
    """全文書のインデックス完了を待つ。失敗した文書は名前を出す。"""
    print("\nインデックス作成を待機中", end="", flush=True)
    for _ in range(120):  # 最大10分
        docs = api("GET", f"/datasets/{dataset_id}/documents?limit=100", key).get("data", [])
        status = {}
        for d in docs:
            status.setdefault(d["indexing_status"], []).append(d["name"])
        done = len(status.get("completed", []))
        errors = status.get("error", [])
        if done + len(errors) >= expected:
            print()
            print(f"完了 {done} 件 / エラー {len(errors)} 件")
            for name in errors:
                print(f"  エラー: {name}")
            return
        print(".", end="", flush=True)
        time.sleep(5)
    print("\nタイムアウト。Dify の画面でステータスを確認してください。")


def main() -> None:
    """ナレッジを作成して60文書を投入する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="A2-eval-corpus", help="ナレッジ名")
    parser.add_argument("--dataset-id", help="既存ナレッジに追加する場合の ID（省略時は新規作成）")
    args = parser.parse_args()

    key = load_key()
    files = sorted(p for p in CORPUS_DIR.iterdir() if p.suffix in (".md", ".pdf"))
    print(f"投入対象: {len(files)} ファイル")

    dataset_id = args.dataset_id or create_dataset(key, args.name)
    print(f"ナレッジ ID: {dataset_id}")

    failed = []
    for i, path in enumerate(files, 1):
        try:
            upload_file(key, dataset_id, path)
            print(f"  [{i:02d}/{len(files)}] {path.name}")
        except RuntimeError as e:
            failed.append(path.name)
            print(f"  [{i:02d}/{len(files)}] 失敗: {path.name}\n      {e}")
        time.sleep(0.3)

    if failed:
        print(f"\nアップロード失敗 {len(failed)} 件。上記のエラーを確認してください。")
        sys.exit(1)

    wait_indexing(key, dataset_id, len(files))


if __name__ == "__main__":
    main()

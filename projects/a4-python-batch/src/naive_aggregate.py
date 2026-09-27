"""【素朴な実装】支店別ファイルを結合して集計する。

**わざと対策を入れていない。** 実務で最初に書くであろう素朴なコードで、
何がどう壊れるかを観察するためのもの（方針書 2-2）。

書いた内容：
- pandas.read_excel / read_csv でそのまま読む
- 結合して groupby で集計する

入れていない対策：
- 文字コードの指定
- ヘッダ行位置の指定
- 日付型の統一
- 全角数字・半角カナの正規化
- 空行・合計行の除去
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console import force_utf8_stdio  # noqa: E402

INPUT_DIR = Path(__file__).resolve().parent.parent / "input" / "excel"


def load_all() -> pd.DataFrame:
    """入力ディレクトリのファイルをすべて読んで結合する。"""
    frames = []
    for path in sorted(INPUT_DIR.iterdir()):
        if path.suffix == ".xlsx":
            df = pd.read_excel(path)
        elif path.suffix == ".csv":
            df = pd.read_csv(path)
        else:
            continue
        df["__file"] = path.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    """読み込み、集計し、結果を表示する。"""
    force_utf8_stdio()  # Windows で日本語の印字が落ちるのを防ぐ（console.py 参照）
    df = load_all()
    print(f"読み込み: {len(df)} 行 / {df['__file'].nunique()} ファイル")
    print(f"列: {list(df.columns)}\n")

    print("=== 先頭5行 ===")
    print(df.head().to_string())

    print("\n=== 支店別の件数合計 ===")
    print(df.groupby("支店")["件数"].sum().to_string())

    print("\n=== 種別ごとの件数合計 ===")
    print(df.groupby("種別")["件数"].sum().to_string())

    print("\n=== 日付列の型 ===")
    print(f"  dtype: {df['日付'].dtype}")
    print(f"  ユニークな型: {set(type(v).__name__ for v in df['日付'].dropna())}")


if __name__ == "__main__":
    main()

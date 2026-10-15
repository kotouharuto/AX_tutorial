"""設定の読み込みと検査。**値は表示しない。**

【なぜ検査を用意するか】A-6a で、手で編集した設定ファイルが黙って壊れていた
（全角スペースで読めない・キー名の打ち間違いは未設定扱い）。
トークンを入れる作業を利用者に頼むなら、正しく入ったかを確かめる手段もセットで渡す。

実行：uv run python src/settings.py
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# 各設定の名前と、値の形の手がかり（先頭の文字列）。中身の正しさまでは分からない
REQUIRED = {
    "SLACK_BOT_TOKEN": "xoxb-",
    "SLACK_APP_TOKEN": "xapp-",
    "GEMINI_API_KEY": "",
}


class SettingsError(RuntimeError):
    """設定が足りない・形が違う。**値そのものはメッセージに入れない。**"""


@dataclass(frozen=True)
class Settings:
    """実行に必要な設定。repr でトークンを出さない。"""

    slack_bot_token: str
    slack_app_token: str
    gemini_api_key: str

    def __repr__(self) -> str:
        return "Settings(slack_bot_token=***, slack_app_token=***, gemini_api_key=***)"


def load_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    """.env を読む。KEY=VALUE とコメントと空行だけを扱う。"""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def find_problems(values: dict[str, str]) -> list[str]:
    """設定の問題点を返す（値は含めない）。空なら問題なし。"""
    problems: list[str] = []
    for name, prefix in REQUIRED.items():
        value = values.get(name, "")
        if not value:
            problems.append(f"{name} が空か、無い")
        elif prefix and not value.startswith(prefix):
            problems.append(f"{name} の先頭が {prefix} ではない（別のトークンを貼った可能性）")
        if value != value.strip() or any(c.isspace() for c in value):
            problems.append(f"{name} に空白が含まれている（全角スペースの混入を含む）")

    # キー名の打ち間違い：想定外のキーがあれば知らせる（A-6a の SHEETS のような誤り）
    for name in values:
        if name not in REQUIRED:
            problems.append(f"想定外のキー {name}（打ち間違いではないか）")
    return problems


def load_settings() -> Settings:
    """設定を読む。環境変数が .env より優先。問題があれば例外にする。"""
    values = load_env_file()
    values.update({k: v for k, v in os.environ.items() if k in REQUIRED})
    problems = find_problems(values)
    if problems:
        raise SettingsError("設定に問題がある：" + "／".join(problems))
    return Settings(
        slack_bot_token=values["SLACK_BOT_TOKEN"],
        slack_app_token=values["SLACK_APP_TOKEN"],
        gemini_api_key=values["GEMINI_API_KEY"],
    )


def main() -> int:
    """設定を検査して結果を出す。値は出さない。"""
    values = load_env_file()
    if not ENV_PATH.exists():
        print(f".env が無い：{ENV_PATH}")
        print("  cp .env.example .env で作ってから、値を入れる")
        return 1
    for name, prefix in REQUIRED.items():
        value = values.get(name, "")
        state = "空" if not value else f"入力あり（{len(value)}文字）"
        shape = ""
        if value and prefix:
            shape = "・先頭OK" if value.startswith(prefix) else f"・★先頭が {prefix} ではない"
        print(f"  {name:16} {state}{shape}")
    problems = find_problems(values)
    if problems:
        print("\n問題：")
        for p in problems:
            print(f"  ★ {p}")
        return 1
    print("\n問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())

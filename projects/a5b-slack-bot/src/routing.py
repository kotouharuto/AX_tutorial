"""振り分け先（分類 → チャンネル）の読み込み。Slack に依存しない。

【対応表をコードに書かない理由】A-3 で「担当を変えたいとき誰が直すか」が論点になった。
GAS では担当をシートに置き、誰でも直せた。n8n ではコードに埋めるしかなく、技術者しか直せなかった。
ここでは routing.json に置き、ファイルの書き換えだけで振り分けを変えられるようにする。

【チャンネルは ID で指定する】名前は変更されることがあり、変わると黙って届かなくなる。
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from classifier import CATEGORIES

BASE_DIR = Path(__file__).resolve().parent.parent
ROUTING_PATH = BASE_DIR / "routing.json"

# Slack のチャンネル ID の形（公開チャンネルは C、非公開は G で始まる）
CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{8,}$")

# 雛形（routing.example.json）の値。形としては正しいので、明示的に弾かないと書き換え忘れが通る。
# A-6b で、フックの参照先が雛形のまま（/path/to/check-command.sh）で黙って何もしていなかったのと同じ型
PLACEHOLDER = "C00000000"


class RoutingError(RuntimeError):
    """振り分けの設定が読めない・誤っている。直す場所が分かる文言にする。"""


@dataclass(frozen=True)
class Routing:
    """振り分けの設定。

    routes:   分類 → 通知先のチャンネル ID
    fallback: 対応が無い分類の通知先（担当が決まっていないもの。人が判断する場所）
    ops:      失敗の通知先（分類や通知に失敗したとき）
    """

    routes: dict[str, str]
    fallback: str
    ops: str

    def resolve(self, category: str) -> tuple[str, bool]:
        """通知先を返す。2つ目は「対応が無く予備の通知先に回したか」。"""
        if category in self.routes:
            return self.routes[category], False
        return self.fallback, True


def load_routing(path: Path = ROUTING_PATH) -> Routing:
    """routing.json を読んで検査する。問題があれば起動時に止める（黙って届かない状態を作らない）。"""
    if not path.exists():
        raise RoutingError(f"{path.name} が無い。routing.example.json をコピーして作る")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RoutingError(f"{path.name} が JSON として読めない（{exc.lineno} 行目）") from None

    routes = data.get("routes")
    if not isinstance(routes, dict):
        raise RoutingError(f"{path.name} に routes（分類 → チャンネル ID）が無い")

    problems: list[str] = []
    def check(label: str, value: object) -> None:
        if value == PLACEHOLDER:
            problems.append(f"{label} が雛形の値 {PLACEHOLDER} のまま（実際のチャンネル ID に書き換える）")
        elif not isinstance(value, str) or not CHANNEL_ID.match(value):
            problems.append(f"{label} {value!r} がチャンネル ID の形ではない")

    for category, channel in routes.items():
        if category not in CATEGORIES:
            problems.append(f"分類「{category}」は定義外（使える分類：{'・'.join(CATEGORIES)}）")
        check(f"「{category}」の通知先", channel)
    for key in ("fallback", "ops"):
        check(f"{key} の通知先", data.get(key))
    if problems:
        raise RoutingError(f"{path.name} の問題：" + "／".join(problems))

    return Routing(routes=dict(routes), fallback=data["fallback"], ops=data["ops"])

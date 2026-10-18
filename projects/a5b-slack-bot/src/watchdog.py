"""Slack との接続を見張る。切れ続けたらプロセスを終わらせ、常駐の仕組みに起動し直させる。

【なぜ要るか】一晩動かした Bot が、深夜から約7時間45分・2,557回、
「つながる → 直後に BrokenPipeError で切れる → 再接続」を繰り返していた。
**プロセスは生きていた**ので、プロセスの生死を見る監視では正常に見える。
同じプロセス内の自動再接続では回復せず、起動し直すと即座に回復した。
→ 「プロセスが動いているか」ではなく「Slack とつながっているか」を見る。

【限界】接続は生きていると報告されるのに、実際にはメッセージが届かない状態は検知できない
（問い合わせが来ない限り区別がつかない）。今回の壊れ方は、ほぼ常に切れている状態だったので検知できる。
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 前回、接続が切れて終了したことを、次の起動に伝えるための記録。
# 切れているときは Slack に知らせられないことがあるので、ファイルに残しておく
MARKER_PATH = BASE_DIR / "output" / "last_watchdog_exit.json"

# 監視で終了するときの終了コード。launchd はこれを見て起動し直す（0 以外なら起動し直す設定）
EXIT_WATCHDOG = 3


class ConnectionWatchdog:
    """接続が切れ続けている時間を数える。時刻は差し替えられる（テストのため）。"""

    def __init__(
        self,
        is_connected: Callable[[], bool],
        threshold_sec: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.is_connected = is_connected
        self.threshold_sec = threshold_sec
        self.now = now
        self.last_connected = now()

    def check(self) -> float | None:
        """つながっていれば None。切れ続けた秒数が閾値を超えたら、その秒数を返す。"""
        if self.is_connected():
            self.last_connected = self.now()
            return None
        down = self.now() - self.last_connected
        return down if down >= self.threshold_sec else None


@dataclass(frozen=True)
class ExitRecord:
    """前回の終了の記録。"""

    at: str
    down_sec: float


def _marker(path: Path | None) -> Path:
    """記録の置き場所。**既定値を呼び出し時に決める。**

    `path: Path = MARKER_PATH` と書くと、既定値は関数を定義した時点で決まり、
    テストで MARKER_PATH を差し替えても効かず、本物の output/ を読み書きしてしまう
    （A-5a で踏んだ落とし穴。ここでも一度同じ書き方をしていた）。
    """
    return path if path is not None else MARKER_PATH


def write_marker(down_sec: float, path: Path | None = None) -> None:
    """終了の理由を残す。"""
    path = _marker(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now().isoformat(timespec="seconds"), "down_sec": round(down_sec)}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def read_marker(path: Path | None = None) -> ExitRecord | None:
    """前回の記録を読む。無ければ None。壊れていても起動は止めない（記録は補助情報なので）。"""
    path = _marker(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ExitRecord(at=str(data["at"]), down_sec=float(data["down_sec"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return ExitRecord(at="不明（記録が壊れていた）", down_sec=-1)


def clear_marker(path: Path | None = None) -> None:
    """記録を消す。知らせ終わったら呼ぶ。"""
    _marker(path).unlink(missing_ok=True)

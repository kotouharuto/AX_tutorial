"""GAS のコード（gas/Code.js）を Node 上で動かす検査を、pytest から実行する。

GAS は手元で実行できないため、部品を偽物に差し替えて doPost を動かす
（中身は tests/gas/run_code.js）。Node が無い環境では飛ばす。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "gas" / "run_code.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node が無い環境")
def test_GASのコードが偽の部品の上で期待どおり動く() -> None:
    result = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "すべて成功" in result.stdout

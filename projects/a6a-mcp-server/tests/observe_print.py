"""print の壊れ方を観察する。結果を表にして出す。テストではなく観察用。"""

import asyncio
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

PROBE = Path(__file__).resolve().parent / "probe_print.py"
TIMEOUT = 15


async def run(where: str) -> str:
    env = get_default_environment()
    env["PRINT_AT"] = where
    server = StdioServerParameters(command=sys.executable, args=[str(PROBE)], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("hello", {"name": "太郎"})
            body = "".join(c.text for c in result.content if hasattr(c, "text"))
            return f"is_error={result.is_error} 本文={body!r}"


async def main() -> None:
    for where in ("none", "startup", "tool", "tool_noeol"):
        started = time.time()
        try:
            outcome = await asyncio.wait_for(run(where), timeout=TIMEOUT)
        except TimeoutError:
            outcome = f"**{TIMEOUT}秒で応答なし（ハング）**"
        except BaseException as exc:  # noqa: BLE001  ExceptionGroup も拾うため
            outcome = f"例外 {type(exc).__name__}: {str(exc)[:160]}"
        print(f"[{where:7}] {time.time() - started:5.1f}秒  {outcome}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

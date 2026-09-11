"""Verify the code execution sandbox and its security constraints (PRD 7.4).

    python scripts/test_sandbox.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import sandbox  # noqa: E402

CASES = [
    (
        "correct solution passes",
        "def solve(a, b):\n    return a + b\n",
        [
            {"name": "adds", "call": "solve(2, 3)", "expected": "5"},
            {"name": "negatives", "call": "solve(-1, 1)", "expected": "0"},
        ],
        True,
    ),
    (
        "wrong solution fails",
        "def solve(a, b):\n    return a - b\n",
        [{"name": "adds", "call": "solve(2, 3)", "expected": "5"}],
        False,
    ),
    (
        "syntax error is caught",
        "def solve(a, b)\n    return a + b\n",
        [{"name": "adds", "call": "solve(2, 3)", "expected": "5"}],
        False,
    ),
    (
        "runtime error is caught",
        "def solve(a, b):\n    return a / 0\n",
        [{"name": "divides", "call": "solve(2, 3)", "expected": "5"}],
        False,
    ),
    (
        "list return value compares",
        "def solve(n):\n    return sorted(n)\n",
        [{"name": "sorts", "call": "solve([3, 1, 2])", "expected": "[1, 2, 3]"}],
        True,
    ),
    (
        "infinite loop hits the time limit",
        "def solve(a, b):\n    while True:\n        pass\n",
        [{"name": "hangs", "call": "solve(1, 2)", "expected": "3"}],
        False,
    ),
    (
        "network access is blocked",
        (
            "import socket\n"
            "def solve():\n"
            "    s = socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
            "    return 'reached network'\n"
        ),
        [{"name": "net", "call": "solve()", "expected": "'reached network'"}],
        False,
    ),
]


async def main() -> int:
    status = await sandbox.status()
    print(f"sandbox status: {status}\n")

    failures = 0
    for name, code, tests, expect_pass in CASES:
        result = await sandbox.run_python(code, tests)
        ok = result["passed"] == expect_pass
        failures += 0 if ok else 1
        detail = f"runner={result.get('runner')} {result.get('runtime_ms', 0)}ms"
        if not result["passed"]:
            reason = result.get("error") or result.get("stderr") or ""
            detail += f" | {str(reason).strip().splitlines()[-1][:70] if reason else 'tests failed'}"
        print(f"{'[ok]' if ok else '[XX]'} {name} — {detail}")

    print(f"\n{len(CASES) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

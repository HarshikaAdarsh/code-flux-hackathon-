"""Isolated Python execution for coding assessments (PRD 7.4).

Primary path: one throwaway Docker container per submission —
    --network none          no network access
    --memory / --cpus       resource caps
    --read-only + tmpfs     no writable filesystem outside /tmp
    --user nobody           non-root
    --pids-limit            no fork bombs
    hard wall-clock timeout enforced by the host

Fallback path: a restricted local subprocess with the same wall-clock timeout,
used only when Docker is not running. Weaker isolation — it exists so a demo
never dies on a missing daemon, and is disabled by SANDBOX_ALLOW_LOCAL_FALLBACK.

Nothing from the user's code is ever eval'd in the API process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

RESULT_MARKER = "__SANDBOX_RESULT__"

# The harness runs *inside* the sandbox. It receives a JSON payload on stdin
# containing the student's code and the test cases.
HARNESS = r'''
import json, sys, io, contextlib, traceback, signal

MARKER = "__SANDBOX_RESULT__"
payload = json.loads(sys.stdin.read())
code = payload["code"]
tests = payload.get("tests") or []
limit = int(payload.get("timeout") or 8)

# Per-step CPU/wall limit for the student's code. Container startup time is
# absorbed by the host timeout, so this budget is theirs alone.
HAS_ALARM = hasattr(signal, "SIGALRM")

class StepTimeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise StepTimeout("Time limit exceeded (%ds) - check for an infinite loop" % limit)

if HAS_ALARM:
    signal.signal(signal.SIGALRM, _on_alarm)

@contextlib.contextmanager
def time_limit():
    if not HAS_ALARM:
        yield
        return
    signal.alarm(limit)
    try:
        yield
    finally:
        signal.alarm(0)

results = []
stdout_buf = io.StringIO()
namespace = {"__name__": "__submission__"}
compile_error = None

try:
    with time_limit(), contextlib.redirect_stdout(stdout_buf):
        exec(compile(code, "submission.py", "exec"), namespace)
except BaseException:
    compile_error = traceback.format_exc(limit=6)

if compile_error is None:
    for i, test in enumerate(tests):
        name = test.get("name") or ("case %d" % (i + 1))
        call = test.get("call", "")
        expected_src = test.get("expected", "")
        entry = {"name": name, "input": call, "expected": expected_src,
                 "passed": False, "actual": None, "error": None}
        try:
            with time_limit(), contextlib.redirect_stdout(stdout_buf):
                actual = eval(call, namespace)
            entry["actual"] = repr(actual)
            try:
                expected = eval(expected_src, {"__builtins__": {}}, {})
            except BaseException:
                expected = expected_src
            if actual == expected or repr(actual) == str(expected_src).strip():
                entry["passed"] = True
            elif (isinstance(actual, float) and isinstance(expected, (int, float))
                  and abs(actual - expected) < 1e-6):
                entry["passed"] = True
        except BaseException:
            entry["error"] = traceback.format_exc(limit=4)
        results.append(entry)

out = stdout_buf.getvalue()
print(MARKER + json.dumps({
    "tests": results,
    "stdout": out[-4000:],
    "compile_error": compile_error,
}))
'''


def _parse_output(raw: str) -> Optional[Dict[str, Any]]:
    idx = raw.rfind(RESULT_MARKER)
    if idx == -1:
        return None
    try:
        return json.loads(raw[idx + len(RESULT_MARKER) :].strip())
    except json.JSONDecodeError:
        return None


def _failure(reason: str, stderr: str = "", elapsed_ms: int = 0) -> Dict[str, Any]:
    return {
        "passed": False,
        "tests": [],
        "stdout": "",
        "stderr": stderr or reason,
        "runtime_ms": elapsed_ms,
        "error": reason,
        "runner": "none",
    }


def docker_available() -> bool:
    return shutil.which("docker") is not None


async def _run_process(
    cmd: List[str], payload: str, timeout: int
) -> tuple[int, str, str, int]:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload.encode()), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise
    elapsed = int((time.monotonic() - started) * 1000)
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
        elapsed,
    )


async def _run_docker(payload: str, timeout: int) -> Dict[str, Any]:
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "none",
        "--memory", f"{settings.sandbox_memory_mb}m",
        "--memory-swap", f"{settings.sandbox_memory_mb}m",
        "--cpus", settings.sandbox_cpus,
        "--pids-limit", "64",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--user", "65534:65534",
        "--security-opt", "no-new-privileges",
        "--workdir", "/tmp",
        settings.sandbox_image,
        "python", "-I", "-c", HARNESS,
    ]
    code, stdout, stderr, elapsed = await _run_process(cmd, payload, timeout)
    parsed = _parse_output(stdout)
    if parsed is None:
        return _failure(
            "Execution produced no result — the program may have crashed.",
            stderr=stderr[-2000:],
            elapsed_ms=elapsed,
        ) | {"runner": "docker", "exit_code": code}
    return {
        "passed": bool(parsed["tests"]) and all(t["passed"] for t in parsed["tests"]),
        "tests": parsed["tests"],
        "stdout": parsed["stdout"],
        "stderr": (parsed.get("compile_error") or stderr)[-2000:],
        "runtime_ms": elapsed,
        "error": parsed.get("compile_error"),
        "runner": "docker",
    }


async def _run_local(payload: str, timeout: int) -> Dict[str, Any]:
    import sys

    cmd = [sys.executable, "-I", "-c", HARNESS]
    code, stdout, stderr, elapsed = await _run_process(cmd, payload, timeout)
    parsed = _parse_output(stdout)
    if parsed is None:
        return _failure(
            "Execution produced no result — the program may have crashed.",
            stderr=stderr[-2000:],
            elapsed_ms=elapsed,
        ) | {"runner": "local", "exit_code": code}
    return {
        "passed": bool(parsed["tests"]) and all(t["passed"] for t in parsed["tests"]),
        "tests": parsed["tests"],
        "stdout": parsed["stdout"],
        "stderr": (parsed.get("compile_error") or stderr)[-2000:],
        "runtime_ms": elapsed,
        "error": parsed.get("compile_error"),
        "runner": "local",
    }


async def run_python(code: str, tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute a submission against its test cases."""
    if not settings.sandbox_enabled:
        return _failure("Code execution is disabled on this server.")
    if len(code) > 50_000:
        return _failure("Submission is too large.")

    code_limit = settings.sandbox_timeout_seconds
    payload = json.dumps({"code": code, "tests": tests, "timeout": code_limit})
    # the host kill is a backstop; the harness enforces the real limit
    timeout = code_limit + settings.sandbox_startup_allowance_seconds

    if docker_available():
        try:
            return await _run_docker(payload, timeout)
        except asyncio.TimeoutError:
            return _failure(
                f"Time limit exceeded ({timeout}s) — check for an infinite loop.",
                elapsed_ms=timeout * 1000,
            ) | {"runner": "docker"}
        except FileNotFoundError:
            logger.warning("docker binary vanished mid-run")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Docker sandbox failed (%s)", exc)

    if not settings.sandbox_allow_local_fallback:
        return _failure(
            "The code execution sandbox is unavailable. Start Docker and retry."
        )

    logger.warning("Docker unavailable — using the local subprocess fallback")
    try:
        return await _run_local(payload, timeout)
    except asyncio.TimeoutError:
        return _failure(
            f"Time limit exceeded ({code_limit}s) — check for an infinite loop.",
            elapsed_ms=timeout * 1000,
        ) | {"runner": "local"}
    except Exception as exc:  # noqa: BLE001
        logger.error("Local sandbox failed: %s", exc)
        return _failure("Could not execute the submission.")


async def status() -> Dict[str, Any]:
    """Sandbox readiness, surfaced on /health."""
    if not settings.sandbox_enabled:
        return {"enabled": False, "runner": "disabled"}
    if not docker_available():
        return {
            "enabled": True,
            "runner": "local-fallback"
            if settings.sandbox_allow_local_fallback
            else "unavailable",
            "docker": False,
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", settings.sandbox_image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
        image_ready = proc.returncode == 0
    except Exception:  # noqa: BLE001
        image_ready = False
    return {
        "enabled": True,
        "runner": "docker",
        "docker": True,
        "image": settings.sandbox_image,
        "image_pulled": image_ready,
        "hint": None
        if image_ready
        else f"run: docker pull {settings.sandbox_image}",
    }

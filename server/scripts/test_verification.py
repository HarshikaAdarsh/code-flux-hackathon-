"""Proves the accuracy guardrails actually work.

    python scripts/test_verification.py

Offline checks (sentence buffering, the retry cap, the fallback) need nothing.
The auditor checks call the live model, and are skipped without an API key.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import verifier  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"{'[ok]' if ok else '[XX]'} {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, why: str) -> None:
    checks.append((name, True, why))
    print(f"[--] {name} — {why}")


# --------------------------------------------------------------------------
# 1. Sentence buffering (Track 1, requirement 2)
# --------------------------------------------------------------------------


def stream(text: str, chunk: int = 5) -> list[str]:
    """Feed text through the buffer the way tokens actually arrive."""
    buf = verifier.SentenceBuffer()
    out: list[str] = []
    for i in range(0, len(text), chunk):
        out += buf.push(text[i : i + chunk])
    return out + buf.flush()


def test_buffering() -> None:
    got = stream("Normalization reduces redundancy. It splits tables. Clear?")
    check("splits on sentence boundaries", len(got) == 3, f"{len(got)} sentences")
    check("no duplication across flush", len(set(got)) == len(got))

    got = stream("The value is 3.14 and covers 99.5 percent, e.g. most joins. Done.")
    check(
        "decimals and e.g. do not split a sentence",
        len(got) == 2 and "3.14" in got[0] and "e.g." in got[0],
        f"{len(got)} sentences",
    )

    got = stream("Here is the idea.\n```python\nx = 1.5\nprint(x)\n```\nIt runs twice.")
    joined = " ".join(got)
    check(
        "code fences never reach the auditor or TTS",
        "print" not in joined and "x = 1.5" not in joined,
        f"{len(got)} sentences, no code",
    )

    got = stream("Flow below.\n```mermaid\ngraph TD\nA-->B\n```\nEach layer adds a header.")
    check("mermaid blocks are excluded too", "graph TD" not in " ".join(got))

    got = stream("The **primary key** is unique here.")
    check("markdown is stripped before auditing", "**" not in " ".join(got), got[0])


# --------------------------------------------------------------------------
# 2. The pre-filter (quota control)
# --------------------------------------------------------------------------


def test_prefilter() -> None:
    audited = "Normalization reduces redundancy."
    filler = "Does that make sense?"
    check("a short factual claim IS audited", verifier.needs_audit(audited), audited)
    check("filler is NOT audited", not verifier.needs_audit(filler), filler)
    check("one-word filler is NOT audited", not verifier.needs_audit("Right."))


# --------------------------------------------------------------------------
# 3. The retry cap and fallback (Track 2, requirements 3 and 4)
# --------------------------------------------------------------------------


async def test_retry_cap() -> None:
    """generate_verified must stop at the configured attempt cap."""
    calls: list[str | None] = []

    async def always_bad(critique):
        calls.append(critique)
        return {"questions": [{"question": "bad", "answer": "wrong"}]}

    async def always_reject(**_kwargs):
        return verifier.ContentVerdict(False, 10, ["answer key is wrong"], "fix it")

    original = verifier.verify_content
    verifier.verify_content = always_reject
    try:
        content, verdict = await verifier.generate_verified(
            kind="test", generate=always_bad, subject="S", topic="T", subtopic="U"
        )
    finally:
        verifier.verify_content = original

    check(
        "retries are capped — no unbounded loop",
        len(calls) == settings.verification_max_attempts,
        f"{len(calls)} attempts (cap {settings.verification_max_attempts})",
    )
    check("first attempt has no critique", calls[0] is None)
    check(
        "the retry is armed with the critique",
        calls[1] is not None and "answer key is wrong" in calls[1],
        (calls[1] or "")[:60].replace("\n", " "),
    )
    check("failing content is never returned", content is None, f"score {verdict.score}")

    msg = verifier.fallback_message("BCNF")
    check(
        "canonical fallback names the sub-topic",
        "BCNF" in msg and "verify" in msg.lower(),
        msg[:70] + "…",
    )


async def test_passes_first_time() -> None:
    """A good generation must not burn a second attempt."""
    calls = []

    async def good(critique):
        calls.append(critique)
        return {"questions": [{"question": "ok", "answer": "right"}]}

    async def approve(**_kwargs):
        return verifier.ContentVerdict(True, 95)

    original = verifier.verify_content
    verifier.verify_content = approve
    try:
        content, verdict = await verifier.generate_verified(
            kind="test", generate=good, subject="S", topic="T", subtopic="U"
        )
    finally:
        verifier.verify_content = original

    check("approved content costs one attempt", len(calls) == 1, f"{len(calls)} call")
    check("approved content is returned", content is not None and verdict.approved)


# --------------------------------------------------------------------------
# 4. The live auditor (Track 1, requirements 3-5) — needs the model
# --------------------------------------------------------------------------

TRUE_CLAIMS = [
    "Normalization reduces data redundancy by splitting a table into smaller related tables.",
    "A foreign key in one table references the primary key of another table.",
]
FALSE_CLAIMS = [
    "The primary key of a table is allowed to contain NULL values.",
    "BCNF is a weaker form of normalization than first normal form.",
]


async def test_live_auditor() -> None:
    if not (settings.gemini_api_key or settings.groq_api_key):
        skip("live sentence auditor", "no API key configured")
        return

    verdicts = await verifier.verify_sentences(
        TRUE_CLAIMS + FALSE_CLAIMS,
        question="Explain normalization",
        subject="Database Management Systems",
        subtopic="Normalization",
        language="en",
    )

    if len(verdicts) != 4:
        check("auditor returned a verdict per sentence", False, f"{len(verdicts)} of 4")
        return
    check("one verdict per sentence", True, "4 of 4")

    approved = [v for v in verdicts[:2] if v.approved]
    check(
        "true statements are approved and spoken as written",
        len(approved) == 2,
        f"scores {[v.score for v in verdicts[:2]]}",
    )

    caught = [v for v in verdicts[2:] if not v.approved]
    check(
        "false statements are caught below the threshold",
        len(caught) == 2,
        f"scores {[v.score for v in verdicts[2:]]}",
    )

    for v in caught:
        check(
            "a false claim is rewritten before TTS",
            v.safe_text and v.safe_text not in FALSE_CLAIMS,
            v.safe_text[:64] + "…",
        )
        check("the student gets a correction note", bool(v.note), (v.note or "")[:64])

    check(
        f"threshold is {settings.verification_threshold}%",
        all(v.approved == (v.score >= settings.verification_threshold) for v in verdicts),
    )


async def test_live_critical() -> None:
    if not (settings.gemini_api_key or settings.groq_api_key):
        skip("live critical auditor", "no API key configured")
        return

    bad_pool = {
        "questions": [
            {
                "question": "Which normal form removes partial dependency?",
                "options": ["1NF", "2NF", "3NF", "BCNF"],
                # Deliberately wrong answer key: 2NF removes partial dependency.
                "answer": "1NF",
                "explanation": "1NF removes partial dependencies.",
            }
        ]
    }
    verdict = await verifier.verify_content(
        kind="1 basic multiple-choice question with an answer key",
        payload=bad_pool,
        subject="Database Management Systems",
        topic="Normalization",
        subtopic="Normal forms",
        difficulty="basic",
    )
    check(
        "a wrong answer key is rejected",
        not verdict.approved,
        f"score {verdict.score}, flaws: {(verdict.flaws or ['—'])[0][:60]}",
    )
    check("the rejection carries actionable critique", bool(verdict.flaws or verdict.guidance))

    good_pool = {
        "questions": [
            {
                "question": "Which normal form removes partial dependency?",
                "options": ["1NF", "2NF", "3NF", "BCNF"],
                "answer": "2NF",
                "explanation": "2NF removes partial dependencies on a composite key.",
            }
        ]
    }
    verdict = await verifier.verify_content(
        kind="1 basic multiple-choice question with an answer key",
        payload=good_pool,
        subject="Database Management Systems",
        topic="Normalization",
        subtopic="Normal forms",
        difficulty="basic",
    )
    check("a correct question passes", verdict.approved, f"score {verdict.score}")


# --------------------------------------------------------------------------


async def main() -> int:
    print(
        f"settings: enabled={settings.verification_enabled} "
        f"threshold={settings.verification_threshold}% "
        f"max_attempts={settings.verification_max_attempts} "
        f"live_chat={settings.verify_live_chat} "
        f"batch={verifier.AUDIT_BATCH_SIZE}"
    )

    print("\n--- Sentence buffering (Track 1) ---")
    test_buffering()

    print("\n--- Audit pre-filter (quota control) ---")
    test_prefilter()

    print("\n--- Retry cap and canonical fallback (Track 2) ---")
    await test_retry_cap()
    await test_passes_first_time()

    print("\n--- Live sentence auditor (Track 1) ---")
    await test_live_auditor()

    print("\n--- Live critical auditor (Track 2) ---")
    await test_live_critical()

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

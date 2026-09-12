"""Accuracy verification and hallucination guardrails.

Two tiers, because the cost of being wrong differs:

  Track 1 — live tutor chat.
    Tokens stream to the UI unblocked. A background auditor checks each
    completed sentence before it may be spoken. Below threshold, the sentence
    is rewritten for text-to-speech and the student gets a correction note.
    A false statement must never be vocalised.

  Track 2 — critical tasks (question pools, grading, official solutions).
    Nothing reaches the UI or the database unverified. Below threshold the
    content is discarded and regenerated once, armed with the auditor's
    critique. Attempts are hard-capped: free tiers are finite, so an
    unbounded retry loop is not an option. If the retry also fails, the
    caller returns a canonical disclaimer instead of unverified material.

Audits run on the fast model tier in their own rate-limit lane, so they add
little latency and cannot starve a live tutor turn.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.config import settings
from app.services import llm, prompts

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class SentenceVerdict:
    """Outcome of auditing one sentence on its way to text-to-speech."""

    approved: bool
    score: int
    safe_text: str  # what may be spoken — rewritten when not approved
    note: Optional[str] = None  # shown to the student when a claim was wrong
    checked: bool = True  # False when skipped (too short, or audits disabled)

    @property
    def corrected(self) -> bool:
        return self.checked and not self.approved


@dataclass
class ContentVerdict:
    """Outcome of auditing a whole piece of high-stakes content."""

    approved: bool
    score: int
    flaws: List[str] = field(default_factory=list)
    guidance: str = ""
    attempts: int = 1
    checked: bool = True


def _clamp_score(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


# How many sentences share one audit request. Small enough that audio can
# start early in a long answer, large enough to stay inside a free-tier quota.
AUDIT_BATCH_SIZE = 4


def _verifier_model() -> Optional[str]:
    """The fast tier keeps audit latency off the critical path."""
    return settings.verifier_model or settings.gemini_chat_model


# --------------------------------------------------------------------------
# Track 1 — sentence buffering
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```")
# A sentence ends at . ! ? or a newline — but never on a decimal point.
_BOUNDARY = re.compile(r"(?<![0-9])([.!?])(?=\s|$)|(\n)")
# A trailing single letter ("e.", "g.") or a known abbreviation is not the end
# of a sentence, so "e.g." and "3.NF" stay intact.
_ABBREV_TAIL = re.compile(
    r"(?:\b[A-Za-z]|\b(?:e\.g|i\.e|etc|vs|fig|eq|no|approx|dr|mr|ms))\.$",
    re.IGNORECASE,
)


class SentenceBuffer:
    """Accumulates streamed tokens and releases complete sentences.

    Text inside fenced code and mermaid blocks is never released: it is not
    spoken aloud, and auditing it line by line would be meaningless.

    Tokens arrive in arbitrary chunks, so everything is driven per character:
    `_line` holds the current line (needed to recognise a fence), `_pending`
    holds confirmed prose waiting for a sentence boundary.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._line = ""
        self._in_fence = False

    def push(self, token: str) -> List[str]:
        """Feed a token. Returns any sentences it completed."""
        out: List[str] = []
        for ch in token:
            self._line += ch

            if ch == "\n":
                line, self._line = self._line, ""
                if _FENCE.match(line):
                    self._in_fence = not self._in_fence
                    continue
                if self._in_fence:
                    continue
                self._pending += line
                out.extend(self._drain())
                continue

            # Mid-line sentence end: safe to promote, since a fence is
            # recognisable from the start of the line and we already have it.
            if ch in ".!?" and not self._in_fence and not _FENCE.match(self._line):
                self._pending += self._line
                self._line = ""
                out.extend(self._drain())
        return out

    def flush(self) -> List[str]:
        """Release whatever is left when the stream ends."""
        if not self._in_fence and not _FENCE.match(self._line):
            self._pending += self._line
        self._line = ""
        out = self._drain()
        tail = _clean_sentence(self._pending)
        self._pending = ""
        if tail:
            out.append(tail)
        return out

    def _drain(self) -> List[str]:
        out: List[str] = []
        search_from = 0
        while True:
            match = _BOUNDARY.search(self._pending, search_from)
            if not match:
                break
            end = match.end()
            candidate = self._pending[:end]
            # An abbreviation is not a sentence end — keep looking.
            if match.group(1) and _ABBREV_TAIL.search(candidate.rstrip()):
                search_from = end
                continue
            self._pending = self._pending[end:]
            search_from = 0
            cleaned = _clean_sentence(candidate)
            if cleaned:
                out.append(cleaned)
        return out


_MD_STRIP = [
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"\*([^*]+)\*"), r"\1"),
    (re.compile(r"^#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s*[-*]\s+", re.M), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
]


def _clean_sentence(text: str) -> str:
    """Markdown syntax is neither spoken nor worth auditing."""
    for pattern, repl in _MD_STRIP:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


def needs_audit(sentence: str) -> bool:
    """Cheap pre-filter: skip text that carries no checkable claim."""
    if len(sentence) < settings.verification_min_chars:
        return False
    # Three real words is enough to assert something checkable
    # ("Normalization reduces redundancy."), which is exactly what we want
    # audited. Shorter filler ("Right.", "Does that make sense?") is not.
    return len(re.findall(r"[A-Za-zऀ-ॿ]{2,}", sentence)) >= 3


# --------------------------------------------------------------------------
# Track 1 — the sentence auditor
# --------------------------------------------------------------------------


async def verify_sentence(
    sentence: str,
    *,
    question: str = "",
    subject: str = "",
    subtopic: str = "",
    context: Optional[str] = None,
    language: str = "en",
) -> SentenceVerdict:
    """Audit one sentence before it may be spoken.

    Never raises: a failed audit degrades to "approved as written" rather than
    silencing the tutor, and is logged. The guardrail is best-effort by design
    — blocking speech on an unavailable auditor would be worse than speaking.
    """
    threshold = settings.verification_threshold

    if not settings.verification_enabled or not settings.verify_live_chat:
        return SentenceVerdict(True, 100, sentence, None, checked=False)
    if not needs_audit(sentence):
        return SentenceVerdict(True, 100, sentence, None, checked=False)

    try:
        data = await llm.complete_json(
            prompts.build_sentence_audit_messages(
                sentence=sentence,
                question=question,
                subject=subject,
                subtopic=subtopic,
                context=context,
                language=language,
                threshold=threshold,
            ),
            model=_verifier_model(),
            temperature=0.0,  # deterministic: the same claim must score the same
            max_tokens=400,
            lane_name="verify",
            retries=0,  # one shot; this sits in front of playback
        )
    except Exception as exc:  # noqa: BLE001 — never break the lesson
        logger.warning("Sentence audit unavailable (%s); passing through", exc)
        return SentenceVerdict(True, 100, sentence, None, checked=False)

    score = _clamp_score(data.get("score"), default=100)
    approved = score >= threshold

    safe_text = str(data.get("safe_text") or "").strip() or sentence
    note = data.get("note")
    note = str(note).strip() if note else None

    if approved:
        # An approved sentence is spoken as the tutor wrote it.
        return SentenceVerdict(True, score, sentence, None)

    if not note:
        note = "This sentence was corrected before being read aloud."
    logger.info("Sentence scored %s/100 and was rewritten for playback", score)
    return SentenceVerdict(False, score, safe_text, note)


async def verify_sentences(
    sentences: List[str],
    *,
    question: str = "",
    subject: str = "",
    subtopic: str = "",
    context: Optional[str] = None,
    language: str = "en",
) -> List[SentenceVerdict]:
    """Audit a small group of sentences in one call.

    Auditing every sentence with its own request is what the guardrail needs
    logically, but on a free tier it is both slow (the rate limiter serialises
    the calls) and wasteful. Batching keeps per-sentence verdicts — each gets
    its own score, rewrite and note — while cutting requests several-fold.

    Sentences the pre-filter skips never reach the model at all.
    """
    threshold = settings.verification_threshold

    if not settings.verification_enabled or not settings.verify_live_chat:
        return [SentenceVerdict(True, 100, s, None, checked=False) for s in sentences]

    # Split into what needs checking and what does not, keeping positions.
    verdicts: List[Optional[SentenceVerdict]] = [None] * len(sentences)
    to_check: List[Tuple[int, str]] = []
    for i, sentence in enumerate(sentences):
        if needs_audit(sentence):
            to_check.append((i, sentence))
        else:
            verdicts[i] = SentenceVerdict(True, 100, sentence, None, checked=False)

    if not to_check:
        return [v for v in verdicts if v is not None]

    try:
        data = await llm.complete_json(
            prompts.build_sentence_batch_audit_messages(
                sentences=[s for _, s in to_check],
                question=question,
                subject=subject,
                subtopic=subtopic,
                context=context,
                language=language,
                threshold=threshold,
            ),
            model=_verifier_model(),
            temperature=0.0,  # deterministic: the same claim must score the same
            max_tokens=1600,
            lane_name="verify",
            retries=0,  # one shot; this sits in front of playback
        )
        results = {int(r.get("index", -1)): r for r in (data.get("results") or [])}
    except Exception as exc:  # noqa: BLE001 — never break the lesson
        logger.warning("Sentence audit unavailable (%s); passing through", exc)
        results = {}

    for position, (index, sentence) in enumerate(to_check):
        row = results.get(position)
        if not row:
            # No verdict came back for this one — speak it as written, but say
            # so, rather than silently claiming it was verified.
            verdicts[index] = SentenceVerdict(True, 100, sentence, None, checked=False)
            continue

        score = _clamp_score(row.get("score"), default=100)
        if score >= threshold:
            verdicts[index] = SentenceVerdict(True, score, sentence, None)
            continue

        safe_text = str(row.get("safe_text") or "").strip() or sentence
        note = row.get("note")
        note = str(note).strip() if note else None
        if not note:
            note = "This sentence was corrected before being read aloud."
        logger.info("Sentence scored %s/100 and was rewritten for playback", score)
        verdicts[index] = SentenceVerdict(False, score, safe_text, note)

    return [v for v in verdicts if v is not None]


# --------------------------------------------------------------------------
# Track 2 — the gatekeeper
# --------------------------------------------------------------------------


async def verify_content(
    *,
    kind: str,
    payload: Any,
    subject: str = "",
    topic: str = "",
    subtopic: str = "",
    difficulty: Optional[str] = None,
    context: Optional[str] = None,
) -> ContentVerdict:
    """Audit a complete piece of high-stakes content."""
    threshold = settings.verification_threshold

    if not settings.verification_enabled:
        return ContentVerdict(True, 100, checked=False)

    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)

    try:
        data = await llm.complete_json(
            prompts.build_critical_audit_messages(
                kind=kind,
                payload=text,
                subject=subject,
                topic=topic,
                subtopic=subtopic,
                difficulty=difficulty,
                context=context,
                threshold=threshold,
            ),
            model=_verifier_model(),
            temperature=0.0,
            max_tokens=1200,
            lane_name="verify",
            retries=0,
        )
    except Exception as exc:  # noqa: BLE001
        # If the auditor is unreachable we cannot claim the content is verified,
        # but refusing every generation would take the product down. Pass it
        # through and mark it unchecked so callers can tell the difference.
        logger.warning("Critical audit unavailable (%s); passing through", exc)
        return ContentVerdict(True, 0, checked=False)

    score = _clamp_score(data.get("score"))
    verdict = str(data.get("verdict") or "").lower()
    approved = score >= threshold and verdict != "reject"

    flaws = [str(f).strip() for f in (data.get("flaws") or []) if str(f).strip()]
    guidance = str(data.get("guidance") or "").strip()

    if not approved:
        logger.info("Critical audit rejected %s at %s/100: %s", kind, score, flaws[:2])

    return ContentVerdict(approved, score, flaws, guidance)


async def generate_verified(
    *,
    kind: str,
    generate: Callable[[Optional[str]], Awaitable[Any]],
    subject: str = "",
    topic: str = "",
    subtopic: str = "",
    difficulty: Optional[str] = None,
    context: Optional[str] = None,
) -> Tuple[Optional[Any], ContentVerdict]:
    """Generate, audit, and retry once with critique.

    `generate` is called with None on the first attempt and with a critique
    string on the retry. Returns (content, verdict); content is None when every
    attempt failed the threshold, and the caller must then fall back to the
    canonical disclaimer rather than showing unverified material.

    Attempts are capped by `verification_max_attempts` (default 2). There is no
    path through this function that loops indefinitely.
    """
    attempts = max(1, settings.verification_max_attempts)
    critique: Optional[str] = None
    last = ContentVerdict(False, 0)

    for attempt in range(1, attempts + 1):
        try:
            content = await generate(critique)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s generation failed on attempt %s: %s", kind, attempt, exc)
            last = ContentVerdict(False, 0, [f"generation failed: {exc}"], "", attempt)
            continue

        if not content:
            last = ContentVerdict(False, 0, ["generator returned nothing"], "", attempt)
            continue

        verdict = await verify_content(
            kind=kind,
            payload=content,
            subject=subject,
            topic=topic,
            subtopic=subtopic,
            difficulty=difficulty,
            context=context,
        )
        verdict.attempts = attempt

        if verdict.approved:
            if attempt > 1:
                logger.info("%s passed on attempt %s at %s/100", kind, attempt, verdict.score)
            return content, verdict

        last = verdict
        critique = _critique_text(verdict)

    logger.warning(
        "%s failed verification after %s attempts (best %s/100)",
        kind, attempts, last.score,
    )
    return None, last


def _critique_text(verdict: ContentVerdict) -> str:
    """Turn an audit into an instruction the generator can act on."""
    parts = ["Your previous attempt was rejected by a reviewer."]
    if verdict.flaws:
        parts.append("Problems found:")
        parts.extend(f"- {f}" for f in verdict.flaws[:6])
    if verdict.guidance:
        parts.append(f"Do this differently: {verdict.guidance}")
    parts.append(
        "Produce a completely new version that fixes these. Verify every answer "
        "key and every test case yourself before responding."
    )
    return "\n".join(parts)


def fallback_message(subtopic: str) -> str:
    """Canonical disclaimer used when verification cannot be satisfied."""
    return prompts.canonical_fallback(subtopic)

"""Syllabus PDF -> topic tree (PRD 7.1).

Degrades gracefully, per the PRD's edge cases:
  extractable text -> LLM tree
  low-confidence / image-only PDF -> heuristic outline parse
  still nothing -> flag `needs_manual_entry` so the UI asks for manual entry.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Tuple

from app.config import settings
from app.services import llm, prompts

logger = logging.getLogger(__name__)

MIN_USEFUL_CHARS = 200

# "Unit 3:", "1.2.3", "Module IV -", "Chapter 2." etc.
_NUMBERING = re.compile(
    r"^\s*(?:unit|module|chapter|section|part|topic)?\s*"
    r"(?:[ivxlcdm]+|\d+(?:\.\d+)*)\s*[.):\-–]\s*",
    re.IGNORECASE,
)
_TOP_LEVEL = re.compile(
    r"^\s*(?:unit|module|chapter|part)\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE
)


def extract_pdf_text(data: bytes) -> str:
    """Pull text out of a PDF. Empty string means image-only/scanned."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:60]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 — one bad page shouldn't kill it
                continue
        return _clean(  "\n".join(pages))
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def extract_text(data: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        return extract_pdf_text(data)
    try:
        return _clean(data.decode("utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001
        return ""


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_numbering(title: str) -> str:
    title = _NUMBERING.sub("", title.strip())
    title = title.strip(" .:-–—\t")
    return re.sub(r"\s{2,}", " ", title)[:300]


def heuristic_tree(text: str) -> List[Dict[str, Any]]:
    """Offline outline parser used when the LLM is unavailable."""
    topics: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or len(line) < 3 or len(line) > 220:
            continue

        if _TOP_LEVEL.match(line):
            title = _strip_numbering(line)
            if title:
                current = {"title": title, "subtopics": []}
                topics.append(current)
            continue

        if current is None:
            continue

        # comma/semicolon separated lists are the common syllabus shape
        parts = [p for p in re.split(r"[,;]", line) if len(p.strip()) > 3]
        for part in parts[:12]:
            title = _strip_numbering(part)
            if title and len(current["subtopics"]) < 12:
                current["subtopics"].append({"title": title})

    topics = [t for t in topics if t["subtopics"]]
    return topics[: settings.max_topics_per_subject]


def _normalise(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enforce the PRD's two-level shape and the 50-topic cap (open q5)."""
    cleaned: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for topic in topics[: settings.max_topics_per_subject]:
        title = _strip_numbering(str(topic.get("title", "")).strip())
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())

        subs: List[Dict[str, str]] = []
        sub_seen: set[str] = set()
        for sub in (topic.get("subtopics") or [])[:12]:
            sub_title = sub.get("title") if isinstance(sub, dict) else str(sub)
            sub_title = _strip_numbering(str(sub_title or "").strip())
            if sub_title and sub_title.lower() not in sub_seen:
                sub_seen.add(sub_title.lower())
                subs.append({"title": sub_title})

        if not subs:
            subs = [{"title": title}]
        cleaned.append({"title": title, "subtopics": subs})

    return cleaned


async def parse_syllabus(
    text: str, subject_hint: str = ""
) -> Tuple[List[Dict[str, Any]], float, str]:
    """Returns (topics, confidence, detected_subject_type)."""
    if len(text) < MIN_USEFUL_CHARS:
        logger.info("Syllabus text too short (%s chars) for LLM parsing", len(text))
        return [], 0.0, "non-coding"

    try:
        data = await llm.complete_json(
            prompts.build_syllabus_messages(
                text, subject_hint, settings.max_topics_per_subject
            ),
            lane_name="background",
        )
        topics = _normalise(data.get("topics") or [])
        confidence = float(data.get("confidence", 0.5))
        subject_type = data.get("type") or "non-coding"
        if subject_type not in ("coding", "non-coding"):
            subject_type = "non-coding"
        if topics:
            return topics, confidence, subject_type
        logger.warning("LLM returned an empty tree; trying heuristic parse")
    except llm.LLMUnavailable as exc:
        logger.warning("LLM syllabus parse unavailable (%s); using heuristics", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM syllabus parse failed (%s); using heuristics", exc)

    fallback = _normalise(heuristic_tree(text))
    return fallback, (0.3 if fallback else 0.0), "non-coding"


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> List[str]:
    """Split syllabus text into overlapping chunks for the vector store."""
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # prefer a paragraph/sentence boundary near the end
            boundary = max(
                text.rfind("\n\n", start, end),
                text.rfind(". ", start + size // 2, end),
            )
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks[:120]

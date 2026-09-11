"""LLM routing layer — Gemini primary, Groq fallback (PRD section 10.1).

Everything in the product that needs a model goes through here:

    complete()        one-shot text
    complete_json()   structured output for syllabus parsing / question gen
    stream()          token-by-token for the tutor chat (PRD section 11 latency)
    embed()           vectors for the pgvector retrieval store

The fallback chain mirrors the PRD diagram exactly:
    Gemini -> (429 or any error) -> Groq -> graceful text-only degradation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from app.config import settings
from app.services.throttle import lane

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEGRADED_MESSAGE = (
    "I'm having trouble reaching the AI service right now. "
    "Give it a moment and try again — your progress is saved."
)


@dataclass
class LLMResult:
    text: str
    provider: str  # gemini | groq | none
    voice_enabled: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


class LLMUnavailable(RuntimeError):
    """Raised when both providers fail and the caller needs structured data."""


# --------------------------------------------------------------------------
# Message helpers
# --------------------------------------------------------------------------


def _to_gemini_contents(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """OpenAI-style messages -> Gemini `contents` (system handled separately)."""
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    return contents


def _system_text(messages: List[Dict[str, str]]) -> Optional[str]:
    parts = [m["content"] for m in messages if m["role"] == "system"]
    return "\n\n".join(parts) if parts else None


# --------------------------------------------------------------------------
# Provider calls
# --------------------------------------------------------------------------


async def _call_gemini(
    messages: List[Dict[str, str]],
    model: str,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
) -> str:
    if not settings.gemini_api_key:
        raise httpx.RequestError("GEMINI_API_KEY not configured")

    body: Dict[str, Any] = {
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    system = _system_text(messages)
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        resp = await client.post(
            f"{GEMINI_BASE}/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise httpx.RequestError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise httpx.RequestError("Gemini returned empty text")
    return text


async def _call_groq(
    messages: List[Dict[str, str]],
    model: str,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
) -> str:
    if not settings.groq_api_key:
        raise httpx.RequestError("GROQ_API_KEY not configured")

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # gpt-oss is a reasoning model and spends completion tokens thinking
        # before it emits any content. "low" roughly halves that overhead,
        # which matters on a free tier.
        "reasoning_effort": "low",
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        resp = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    text = (data["choices"][0]["message"]["content"] or "").strip()
    if not text:
        raise httpx.RequestError("Groq returned empty text")
    return text


# --------------------------------------------------------------------------
# Public API — non-streaming
# --------------------------------------------------------------------------


async def complete(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    lane_name: str = "interactive",
) -> LLMResult:
    """Gemini, then Groq, then a safe degraded message."""
    await lane(lane_name).acquire()
    gemini_model = model or (
        settings.gemini_json_model if json_mode else settings.gemini_chat_model
    )

    try:
        text = await _call_gemini(
            messages, gemini_model, json_mode, temperature, max_tokens
        )
        return LLMResult(text=text, provider="gemini")
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Gemini %s -> %s, falling back to Groq",
            gemini_model,
            exc.response.status_code,
        )
    except (httpx.RequestError, KeyError, IndexError, asyncio.TimeoutError) as exc:
        logger.warning("Gemini call failed (%s), falling back to Groq", exc)

    try:
        text = await _call_groq(
            messages,
            settings.groq_fallback_model,
            json_mode,
            temperature,
            max_tokens,
        )
        return LLMResult(text=text, provider="groq")
    except Exception as exc:  # noqa: BLE001 — last line of defence
        logger.error("Groq fallback failed (%s); returning degraded response", exc)

    return LLMResult(text=DEGRADED_MESSAGE, provider="none", voice_enabled=False)


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Parse JSON that may be wrapped in prose or a markdown fence."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = _JSON_FENCE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise LLMUnavailable("Model did not return parseable JSON")


async def complete_json(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    lane_name: str = "background",
    retries: int = 1,
) -> Any:
    """Structured output for syllabus parsing and question generation."""
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        result = await complete(
            messages,
            model=model or settings.gemini_json_model,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
            lane_name=lane_name,
        )
        if result.provider == "none":
            raise LLMUnavailable("Both LLM providers are unavailable")
        try:
            return _extract_json(result.text)
        except LLMUnavailable as exc:
            last_error = exc
            logger.warning("JSON parse failed on attempt %s", attempt + 1)
    raise last_error or LLMUnavailable("Could not obtain JSON from the model")


# --------------------------------------------------------------------------
# Public API — streaming (PRD section 11: tutor turns must stream)
# --------------------------------------------------------------------------


async def _stream_gemini(
    messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[str, None]:
    if not settings.gemini_api_key:
        raise httpx.RequestError("GEMINI_API_KEY not configured")

    body: Dict[str, Any] = {
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    system = _system_text(messages)
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        async with client.stream(
            "POST",
            f"{GEMINI_BASE}/{model}:streamGenerateContent?alt=sse",
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for cand in chunk.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if part.get("text"):
                            yield part["text"]


async def _stream_groq(
    messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int
) -> AsyncGenerator[str, None]:
    if not settings.groq_api_key:
        raise httpx.RequestError("GROQ_API_KEY not configured")

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        async with client.stream(
            "POST",
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = chunk["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta


async def stream(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    lane_name: str = "interactive",
) -> AsyncGenerator[Dict[str, str], None]:
    """Yields {"type": "token"|"provider"|"error", "value": ...}.

    Falls back to Groq only if Gemini fails *before* emitting any token —
    switching providers mid-sentence would produce incoherent output.
    """
    await lane(lane_name).acquire()
    gemini_model = model or settings.gemini_chat_model

    emitted = False
    try:
        async for token in _stream_gemini(
            messages, gemini_model, temperature, max_tokens
        ):
            if not emitted:
                emitted = True
                yield {"type": "provider", "value": "gemini"}
            yield {"type": "token", "value": token}
        if emitted:
            return
    except Exception as exc:  # noqa: BLE001
        if emitted:
            logger.error("Gemini stream broke mid-response: %s", exc)
            yield {"type": "error", "value": "stream_interrupted"}
            return
        logger.warning("Gemini stream failed (%s), falling back to Groq", exc)

    try:
        async for token in _stream_groq(
            messages, settings.groq_fallback_model, temperature, max_tokens
        ):
            if not emitted:
                emitted = True
                yield {"type": "provider", "value": "groq"}
            yield {"type": "token", "value": token}
        if emitted:
            return
    except Exception as exc:  # noqa: BLE001
        logger.error("Groq stream failed: %s", exc)

    yield {"type": "provider", "value": "none"}
    yield {"type": "token", "value": DEGRADED_MESSAGE}
    yield {"type": "error", "value": "providers_unavailable"}


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------

EMBEDDING_DIM = 768


def _hash_embedding(text: str) -> List[float]:
    """Deterministic offline fallback so retrieval never hard-fails.

    Not semantic — it only keeps the pipeline alive when no key is set.
    """
    vec = [0.0] * EMBEDDING_DIM
    for token in re.findall(r"\w+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        idx = struct.unpack("<I", digest[:4])[0] % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


async def embed(texts: List[str], *, lane_name: str = "background") -> List[List[float]]:
    """Gemini embeddings with a deterministic local fallback."""
    if not texts:
        return []

    if not settings.gemini_api_key:
        return [_hash_embedding(t) for t in texts]

    await lane(lane_name).acquire()
    model = settings.gemini_embed_model
    body = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t[:8000]}]},
                "taskType": "RETRIEVAL_DOCUMENT",
                # gemini-embedding-001 defaults to 3072 dims; the content_chunks
                # column is Vector(768), so pin the size explicitly.
                "outputDimensionality": EMBEDDING_DIM,
            }
            for t in texts
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{GEMINI_BASE}/{model}:batchEmbedContents",
                headers={
                    "x-goog-api-key": settings.gemini_api_key,
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        vectors = [e["values"] for e in data.get("embeddings", [])]
        if len(vectors) == len(texts):
            return vectors
        logger.warning("Embedding count mismatch; using fallback")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding call failed (%s); using fallback", exc)

    return [_hash_embedding(t) for t in texts]


async def health_check() -> Dict[str, Any]:
    """Pre-demo health check (PRD section 10.1)."""

    async def ping_gemini() -> Dict[str, Any]:
        if not settings.gemini_api_key:
            return {"configured": False, "ok": False, "detail": "no key"}
        try:
            await _call_gemini(
                [{"role": "user", "content": "ping"}],
                settings.gemini_chat_model,
                False,
                0.0,
                # generous enough that a reasoning model still emits content
                256,
            )
            return {"configured": True, "ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "ok": False, "detail": str(exc)[:200]}

    async def ping_groq() -> Dict[str, Any]:
        if not settings.groq_api_key:
            return {"configured": False, "ok": False, "detail": "no key"}
        try:
            await _call_groq(
                [{"role": "user", "content": "ping"}],
                settings.groq_fallback_model,
                False,
                0.0,
                # generous enough that a reasoning model still emits content
                256,
            )
            return {"configured": True, "ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "ok": False, "detail": str(exc)[:200]}

    gemini, groq = await asyncio.gather(ping_gemini(), ping_groq())
    return {
        "gemini": gemini,
        "groq": groq,
        "degraded": not (gemini["ok"] or groq["ok"]),
    }

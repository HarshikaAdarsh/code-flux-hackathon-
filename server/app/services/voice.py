"""Multilingual voice: STT in, TTS out (PRD 7.5).

STT — Groq Whisper (free tier: 2,000 audio requests/day).
TTS — edge-tts (free, no key, good English + Hindi voices).

Phase 1 languages: English and Hindi (PRD open question 1). If synthesis fails
for a language we return voice_enabled=false so the client can fall back to text
rather than failing silently (PRD section 11).
"""

from __future__ import annotations

import base64
import io
import logging
import struct
from typing import Dict, Optional, Tuple

import httpx

from app.config import settings
from app.services import storage

logger = logging.getLogger(__name__)

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_TTS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# edge-tts voices per supported language
VOICES: Dict[str, str] = {
    "en": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural",
}

MAX_AUDIO_BYTES = 25 * 1024 * 1024


class VoiceError(RuntimeError):
    pass


def normalise_language(code: Optional[str], fallback: str = "en") -> str:
    if not code:
        return fallback
    base = code.split("-")[0].lower()
    return base if base in settings.supported_languages else fallback


async def transcribe(
    audio: bytes, filename: str = "audio.webm", language: Optional[str] = None
) -> Tuple[str, str]:
    """Returns (text, detected_language)."""
    if not audio:
        raise VoiceError("Empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise VoiceError("Audio file is too large (max 25MB)")
    if not settings.groq_api_key:
        raise VoiceError("Speech-to-text is not configured (GROQ_API_KEY missing)")

    data = {"model": settings.groq_stt_model, "response_format": "verbose_json"}
    if language:
        data["language"] = normalise_language(language)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": (filename, audio, "application/octet-stream")},
                data=data,
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Groq STT %s: %s", exc.response.status_code, exc.response.text[:300])
        raise VoiceError("Speech-to-text service is unavailable right now") from exc
    except httpx.RequestError as exc:
        logger.error("Groq STT request failed: %s", exc)
        raise VoiceError("Could not reach the speech-to-text service") from exc

    text = (payload.get("text") or "").strip()
    detected = normalise_language(payload.get("language"), language or "en")
    if not text:
        raise VoiceError("Could not hear anything in that recording")
    return text, detected


def _strip_markdown(text: str) -> str:
    """TTS should read prose, not markdown syntax or code blocks."""
    import re

    text = re.sub(r"```mermaid.*?```", " (diagram shown on screen) ", text, flags=re.S)
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _pcm_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Gemini TTS returns headerless 16-bit PCM; browsers need a WAV header."""
    byte_rate = sample_rate * channels * 2
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


async def _synthesize_edge(text: str, voice: str) -> Optional[Tuple[bytes, str]]:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return (bytes(chunks), ".mp3") if chunks else None


async def _synthesize_gemini(text: str) -> Optional[Tuple[bytes, str]]:
    """Fallback TTS on the Gemini key. Detects language from the text itself."""
    if not settings.gemini_api_key:
        return None

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            GEMINI_TTS_URL.format(model=settings.gemini_tts_model),
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": settings.gemini_tts_voice
                            }
                        }
                    },
                },
            },
        )
        resp.raise_for_status()
        part = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]

    pcm = base64.b64decode(part["data"])
    if not pcm:
        return None

    mime = part.get("mimeType", "")
    rate = 24000
    for token in mime.split(";"):
        if "rate=" in token:
            try:
                rate = int(token.split("rate=")[1].strip())
            except ValueError:
                pass
    return _pcm_to_wav(pcm, rate), ".wav"


async def synthesize(
    text: str, language: str = "en", voice: Optional[str] = None
) -> Optional[str]:
    """Generate speech; returns a public URL, or None if synthesis failed.

    edge-tts first (free and unmetered), Gemini TTS as the fallback — the edge
    endpoint is unofficial and has rejected client versions before, and losing
    voice mid-demo is worse than spending a little Gemini quota.
    """
    spoken = _strip_markdown(text)[:3000]
    if not spoken:
        return None

    lang = normalise_language(language)
    selected = voice or VOICES.get(lang, VOICES["en"])

    for name, factory in (
        ("edge-tts", lambda: _synthesize_edge(spoken, selected)),
        ("gemini-tts", lambda: _synthesize_gemini(spoken)),
    ):
        try:
            result = await factory()
            if result:
                audio, extension = result
                url, _ = storage.save_audio(audio, extension)
                return url
            logger.warning("%s produced no audio for %s", name, lang)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s failed for %s: %s", name, lang, exc)

    logger.warning("All TTS providers failed for %s; client should use text", lang)
    return None


async def status() -> Dict[str, object]:
    return {
        "stt": {
            "provider": "groq-whisper",
            "configured": bool(settings.groq_api_key),
            "model": settings.groq_stt_model,
        },
        "tts": {
            "provider": "edge-tts",
            "fallback": f"gemini-tts ({settings.gemini_tts_model})",
            "voices": VOICES,
        },
        "languages": settings.supported_languages,
    }

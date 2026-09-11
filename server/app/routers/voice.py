"""Multilingual voice assistant: mic in -> voice out (PRD 7.5)."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.deps import CurrentUser, DbSession
from app.schemas import SpeakRequest, TranscriptionOut, VoiceChatOut
from app.services import llm, teaching, voice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    user: CurrentUser,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
):
    """Speech to text via Groq Whisper."""
    audio = await file.read()
    try:
        text, detected = await voice.transcribe(
            audio, file.filename or "audio.webm", language or user.preferred_language
        )
    except voice.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TranscriptionOut(text=text, language=detected, provider="groq-whisper")


@router.post("/speak")
async def speak(payload: SpeakRequest, user: CurrentUser):
    """Text to speech. Returns an audio URL, or voice_enabled=false to fall
    back to text if synthesis fails for the requested language."""
    language = voice.normalise_language(payload.language, user.preferred_language)
    url = await voice.synthesize(payload.text, language, payload.voice)
    if url is None:
        return JSONResponse(
            status_code=200,
            content={
                "audio_url": None,
                "voice_enabled": False,
                "language": language,
                "message": (
                    "Voice isn't available for this language right now — "
                    "showing the text instead."
                ),
            },
        )
    return {"audio_url": url, "voice_enabled": True, "language": language}


@router.post("/chat", response_model=VoiceChatOut)
async def voice_chat(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    subject_id: Optional[uuid.UUID] = Form(None),
    subtopic_id: Optional[uuid.UUID] = Form(None),
    session_id: Optional[uuid.UUID] = Form(None),
    language: Optional[str] = Form(None),
    speak_reply: bool = Form(True),
):
    """One round trip of the voice loop: STT -> tutor -> TTS (PRD 7.5)."""
    audio = await file.read()
    try:
        transcript, detected = await voice.transcribe(
            audio, file.filename or "audio.webm", language or user.preferred_language
        )
    except voice.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    subject, topic, subtopic = await teaching.resolve_scope(
        db, user, subject_id=subject_id, subtopic_id=subtopic_id
    )
    session = await teaching.get_or_create_session(
        db,
        user,
        session_id=session_id,
        subject=subject,
        subtopic=subtopic,
        mode="voice",
        language=detected,
    )
    messages = await teaching.build_messages(
        db,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        session=session,
        user_message=transcript,
        language=detected,
    )
    # spoken answers should be shorter than written ones
    messages[0]["content"] += (
        "\n\nTHIS TURN IS SPOKEN ALOUD: keep it under 150 words, use plain "
        "sentences, no markdown tables, no diagrams, no long code blocks."
    )
    result = await llm.complete(messages, lane_name="interactive", max_tokens=900)

    teaching.append_message(session, "user", transcript)
    teaching.append_message(session, "assistant", result.text, result.provider)
    await db.flush()

    audio_url = None
    if speak_reply and result.voice_enabled:
        audio_url = await voice.synthesize(result.text, detected)

    return VoiceChatOut(
        transcript=transcript,
        language=detected,
        reply=result.text,
        session_id=session.id,
        audio_url=audio_url,
        voice_enabled=audio_url is not None,
        provider=result.provider,
    )


@router.get("/languages")
async def languages():
    return await voice.status()

"""Teaching chat — topic-scoped, streaming, multilingual (PRD 7.2)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.database import SessionLocal
from app.deps import CurrentUser, DbSession
from app.models import ChatSession, User
from app.schemas import ChatSessionOut, TeachRequest, TeachResponse
from app.services import llm, prompts, teaching
from app.services.voice import normalise_language

logger = logging.getLogger(__name__)
router = APIRouter(tags=["teaching"])


def _user_message(payload: TeachRequest, subtopic_title: Optional[str]) -> str:
    if payload.message and payload.message.strip():
        return payload.message.strip()
    if subtopic_title:
        return prompts.lesson_opener(subtopic_title)
    raise HTTPException(
        status_code=400,
        detail="Provide a message, or a subtopic_id to start a lesson",
    )


@router.post("/teach", response_model=TeachResponse)
async def teach(payload: TeachRequest, user: CurrentUser, db: DbSession):
    """Start or continue a lesson. Use /teach/stream for token-by-token output."""
    language = normalise_language(payload.language, user.preferred_language)
    subject, topic, subtopic = await teaching.resolve_scope(
        db, user, subject_id=payload.subject_id, subtopic_id=payload.subtopic_id
    )
    session = await teaching.get_or_create_session(
        db,
        user,
        session_id=payload.session_id,
        subject=subject,
        subtopic=subtopic,
        mode=payload.mode,
        language=language,
    )
    message = _user_message(payload, subtopic.title if subtopic else None)

    messages = await teaching.build_messages(
        db,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        session=session,
        user_message=message,
        language=language,
        style=payload.style,
    )
    result = await llm.complete(messages, lane_name="interactive", max_tokens=2048)

    teaching.append_message(session, "user", message)
    teaching.append_message(session, "assistant", result.text, result.provider)
    await db.flush()

    return TeachResponse(
        session_id=session.id,
        reply=result.text,
        provider=result.provider,
        voice_enabled=result.voice_enabled,
        language=language,
        messages=session.messages,
    )


@router.post("/teach/stream")
async def teach_stream(payload: TeachRequest, user: CurrentUser, db: DbSession):
    """Server-sent events: {type: token|provider|done|error}.

    The response is persisted after the stream closes, in its own session, so a
    disconnected client never leaves a half-written transcript.
    """
    language = normalise_language(payload.language, user.preferred_language)
    subject, topic, subtopic = await teaching.resolve_scope(
        db, user, subject_id=payload.subject_id, subtopic_id=payload.subtopic_id
    )
    session = await teaching.get_or_create_session(
        db,
        user,
        session_id=payload.session_id,
        subject=subject,
        subtopic=subtopic,
        mode=payload.mode,
        language=language,
    )
    message = _user_message(payload, subtopic.title if subtopic else None)
    messages = await teaching.build_messages(
        db,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        session=session,
        user_message=message,
        language=language,
        style=payload.style,
    )
    session_id = session.id
    user_id = user.id
    await db.commit()

    async def event_stream():
        collected: List[str] = []
        provider = "unknown"

        yield f"data: {json.dumps({'type': 'session', 'session_id': str(session_id)})}\n\n"
        try:
            async for event in llm.stream(messages, lane_name="interactive"):
                if event["type"] == "provider":
                    provider = event["value"]
                elif event["type"] == "token":
                    collected.append(event["value"])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("Teaching stream failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'value': 'stream_failed'})}\n\n"

        reply = "".join(collected).strip()
        if reply:
            async with SessionLocal() as write_db:
                stored = await write_db.scalar(
                    select(ChatSession).where(
                        ChatSession.id == session_id, ChatSession.user_id == user_id
                    )
                )
                if stored is not None:
                    teaching.append_message(stored, "user", message)
                    teaching.append_message(stored, "assistant", reply, provider)
                    await write_db.commit()

        yield (
            "data: "
            + json.dumps({"type": "done", "provider": provider, "length": len(reply)})
            + "\n\n"
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/teach/sessions", response_model=List[ChatSessionOut])
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
    subject_id: Optional[uuid.UUID] = None,
    subtopic_id: Optional[uuid.UUID] = None,
    limit: int = 20,
):
    stmt = select(ChatSession).where(ChatSession.user_id == user.id)
    if subject_id:
        stmt = stmt.where(ChatSession.subject_id == subject_id)
    if subtopic_id:
        stmt = stmt.where(ChatSession.subtopic_id == subtopic_id)
    stmt = stmt.order_by(ChatSession.updated_at.desc()).limit(min(limit, 100))
    return (await db.scalars(stmt)).all()


@router.get("/teach/sessions/{session_id}", response_model=ChatSessionOut)
async def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession):
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.delete("/teach/sessions/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession):
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    await db.delete(session)

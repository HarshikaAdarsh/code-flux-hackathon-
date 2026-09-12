"""Teaching chat — topic-scoped, streaming, multilingual (PRD 7.2)."""

from __future__ import annotations

import asyncio
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
from app.services import llm, prompts, teaching, verifier
from app.services.voice import normalise_language

logger = logging.getLogger(__name__)
router = APIRouter(tags=["teaching"])


def _verdict_frames(first_index: int, task, notes: List[str]) -> List[str]:
    """Turn a finished batch audit into the SSE frames the client consumes.

    `speak` is what may go to text-to-speech: the original sentence when it
    passed, a corrected rewrite when it did not. A failed audit degrades to
    "speak it as written" rather than silencing the tutor — an unreachable
    auditor should not take the lesson down with it.
    """
    try:
        verdicts = task.result()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sentence audit task failed: %s", exc)
        return []

    frames: List[str] = []
    for offset, verdict in enumerate(verdicts):
        if verdict.note:
            notes.append(verdict.note)
        frames.append(
            "data: "
            + json.dumps({
                "type": "verified",
                "index": first_index + offset,
                "approved": verdict.approved,
                "score": verdict.score,
                "speak": verdict.safe_text,
                "note": verdict.note,
                "checked": verdict.checked,
            })
            + "\n\n"
        )
    return frames


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
    messages, context_text = await teaching.build_messages_with_context(
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
    subject_name = subject.name if subject else ""
    subtopic_name = subtopic.title if subtopic else ""
    await db.commit()

    async def event_stream():
        collected: List[str] = []
        provider = "unknown"

        # Track 1: tokens stream to the client untouched, while each completed
        # sentence is audited in the background before it may be spoken.
        buffer = verifier.SentenceBuffer()
        audits: List[tuple] = []  # (first_index, asyncio.Task)
        notes: List[str] = []
        pending: List[str] = []  # sentences waiting to fill a batch
        next_index = 0

        def queue_sentence(sentence: str) -> None:
            """Group sentences so one audit covers several, keeping us inside
            the free-tier rate limit without losing per-sentence verdicts."""
            pending.append(sentence)
            if len(pending) >= verifier.AUDIT_BATCH_SIZE:
                dispatch()

        def dispatch() -> None:
            nonlocal next_index
            if not pending:
                return
            batch = list(pending)
            pending.clear()
            first_index = next_index
            next_index += len(batch)
            task = asyncio.create_task(
                verifier.verify_sentences(
                    batch,
                    question=message,
                    subject=subject_name,
                    subtopic=subtopic_name,
                    context=context_text,
                    language=language,
                )
            )
            audits.append((first_index, task))

        def drain_finished() -> List[str]:
            """Emit verdicts for audits that have completed, without waiting."""
            frames: List[str] = []
            still_running = []
            for first_index, task in audits:
                if not task.done():
                    still_running.append((first_index, task))
                    continue
                frames.extend(_verdict_frames(first_index, task, notes))
            audits[:] = still_running
            return frames

        yield f"data: {json.dumps({'type': 'session', 'session_id': str(session_id)})}\n\n"
        try:
            async for event in llm.stream(messages, lane_name="interactive"):
                if event["type"] == "provider":
                    provider = event["value"]
                elif event["type"] == "token":
                    collected.append(event["value"])
                    for sentence in buffer.push(event["value"]):
                        queue_sentence(sentence)

                # The token goes out first — audits never delay the transcript.
                yield f"data: {json.dumps(event)}\n\n"
                for frame in drain_finished():
                    yield frame
        except Exception as exc:  # noqa: BLE001
            logger.error("Teaching stream failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'value': 'stream_failed'})}\n\n"

        for sentence in buffer.flush():
            pending.append(sentence)
        dispatch()  # audit whatever is left, however small the batch

        # The reply is complete; now wait for any audits still in flight so the
        # client has a verdict for every spoken sentence before playback ends.
        if audits:
            await asyncio.gather(*(task for _, task in audits), return_exceptions=True)
            for frame in drain_finished():
                yield frame

        reply = "".join(collected).strip()
        if notes:
            # Requirement 5: a visible correction note on the transcript itself.
            reply += "\n\n---\n" + "\n".join(f"> ⚠️ {n}" for n in notes)
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

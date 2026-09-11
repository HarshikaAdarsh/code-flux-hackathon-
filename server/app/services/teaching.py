"""Shared teaching-session logic used by both the chat and voice routers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, Subject, Subtopic, Topic, User
from app.services import prompts, retrieval
from app.services.assessment import decayed_mastery


async def resolve_scope(
    db: AsyncSession,
    user: User,
    *,
    subject_id: Optional[uuid.UUID],
    subtopic_id: Optional[uuid.UUID],
) -> Tuple[Optional[Subject], Optional[Topic], Optional[Subtopic]]:
    """Resolve and authorise the subject/topic/sub-topic a chat is scoped to."""
    subtopic = topic = subject = None

    if subtopic_id:
        row = (
            await db.execute(
                select(Subtopic, Topic, Subject)
                .join(Topic, Topic.id == Subtopic.topic_id)
                .join(Subject, Subject.id == Topic.subject_id)
                .where(Subtopic.id == subtopic_id, Subject.user_id == user.id)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Sub-topic not found")
        subtopic, topic, subject = row
    elif subject_id:
        subject = await db.scalar(
            select(Subject).where(
                Subject.id == subject_id, Subject.user_id == user.id
            )
        )
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found")

    return subject, topic, subtopic


async def get_or_create_session(
    db: AsyncSession,
    user: User,
    *,
    session_id: Optional[uuid.UUID],
    subject: Optional[Subject],
    subtopic: Optional[Subtopic],
    mode: str,
    language: str,
) -> ChatSession:
    if session_id:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user.id
            )
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        session.mode = mode
        session.language = language
        return session

    if subtopic is not None:
        existing = await db.scalar(
            select(ChatSession)
            .where(
                ChatSession.user_id == user.id,
                ChatSession.subtopic_id == subtopic.id,
            )
            .order_by(ChatSession.created_at.desc())
        )
        if existing is not None:
            existing.mode = mode
            existing.language = language
            return existing

    session = ChatSession(
        user_id=user.id,
        subject_id=subject.id if subject else None,
        subtopic_id=subtopic.id if subtopic else None,
        mode=mode,
        language=language,
        title=subtopic.title if subtopic else (subject.name if subject else "Study chat"),
        messages=[],
    )
    db.add(session)
    await db.flush()
    return session


def append_message(
    session: ChatSession, role: str, content: str, provider: Optional[str] = None
) -> None:
    """JSONB columns need reassignment — in-place append is not tracked."""
    entry: Dict[str, Any] = {
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if provider:
        entry["provider"] = provider
    session.messages = list(session.messages or []) + [entry]


async def weak_areas_for_subject(
    db: AsyncSession, subject_id: Optional[uuid.UUID], limit: int = 5
) -> List[str]:
    if not subject_id:
        return []
    rows = (
        await db.execute(
            select(Subtopic.title, Subtopic.mastery_score)
            .join(Topic, Topic.id == Subtopic.topic_id)
            .where(
                Topic.subject_id == subject_id,
                Subtopic.mastery_score > 0,
                Subtopic.mastery_score < 50,
            )
            .order_by(Subtopic.mastery_score)
            .limit(limit)
        )
    ).all()
    return [title for title, _ in rows]


async def build_messages(
    db: AsyncSession,
    *,
    subject: Optional[Subject],
    topic: Optional[Topic],
    subtopic: Optional[Subtopic],
    session: ChatSession,
    user_message: str,
    language: str,
    style: str = "default",
) -> List[Dict[str, str]]:
    context_chunks: List[str] = []
    if subject is not None:
        query = f"{subtopic.title if subtopic else ''} {user_message}".strip()
        context_chunks = await retrieval.search(
            db, subject_id=subject.id, query=query, limit=3
        )

    mastery = (
        decayed_mastery(subtopic.mastery_score, subtopic.mastery_updated_at)
        if subtopic
        else None
    )

    return prompts.build_tutor_messages(
        subject=subject.name if subject else "General study",
        subject_type=subject.type if subject else "non-coding",
        topic=topic.title if topic else "",
        subtopic=subtopic.title if subtopic else "",
        language=language,
        history=list(session.messages or []),
        user_message=user_message,
        context_chunks=context_chunks,
        mastery_score=mastery,
        weak_areas=await weak_areas_for_subject(
            db, subject.id if subject else None
        ),
        style=style,
    )

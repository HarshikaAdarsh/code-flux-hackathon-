"""Subject containers, syllabus upload and the topic tree (PRD 7.1)."""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import ContentChunk, Subject, Subtopic, Topic
from app.schemas import (
    ParsedTreeOut,
    SubjectCreate,
    SubjectListItem,
    SubjectTreeOut,
    SubjectUpdate,
    SubtopicOut,
    TopicIn,
    TopicOut,
    TreeReplace,
)
from app.services import retrieval, storage, syllabus
from app.services.assessment import decayed_mastery

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subjects", tags=["subjects"])


async def load_subject(
    db, subject_id: uuid.UUID, user_id: uuid.UUID, *, with_tree: bool = False
) -> Subject:
    stmt = select(Subject).where(
        Subject.id == subject_id, Subject.user_id == user_id
    )
    if with_tree:
        stmt = stmt.options(selectinload(Subject.topics).selectinload(Topic.subtopics))
    subject = await db.scalar(stmt)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


def _write_tree(subject: Subject, topics: List[TopicIn]) -> None:
    """Replace a subject's tree, enforcing the PRD's 50-topic cap."""
    if len(topics) > settings.max_topics_per_subject:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A subject can have at most {settings.max_topics_per_subject} "
                "topics. Merge the finer items into sub-topics."
            ),
        )
    subject.topics = [
        Topic(
            title=t.title.strip()[:300],
            order_index=i,
            subtopics=[
                Subtopic(title=s.title.strip()[:300], order_index=j)
                for j, s in enumerate(t.subtopics or [])
            ]
            or [Subtopic(title=t.title.strip()[:300], order_index=0)],
        )
        for i, t in enumerate(topics)
        if t.title.strip()
    ]


async def _reload_tree(db, subject_id: uuid.UUID, user_id: uuid.UUID) -> SubjectTreeOut:
    """Re-read the subject with its tree eagerly loaded.

    After a flush, server-default columns (created_at) and collections are
    expired; touching them during serialization would trigger a lazy load
    outside the async greenlet context.
    """
    await db.flush()
    subject = await db.scalar(
        select(Subject)
        .where(Subject.id == subject_id, Subject.user_id == user_id)
        .options(selectinload(Subject.topics).selectinload(Topic.subtopics))
        .execution_options(populate_existing=True)
    )
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_tree(subject)


def _serialize_tree(subject: Subject) -> SubjectTreeOut:
    topics: List[TopicOut] = []
    total_sub = done_sub = mastery_sum = 0

    for topic in sorted(subject.topics, key=lambda t: t.order_index):
        subs = []
        for st in sorted(topic.subtopics, key=lambda s: s.order_index):
            mastery = decayed_mastery(st.mastery_score, st.mastery_updated_at)
            total_sub += 1
            done_sub += 1 if st.is_completed else 0
            mastery_sum += mastery
            subs.append(
                SubtopicOut(
                    id=st.id,
                    title=st.title,
                    order_index=st.order_index,
                    is_completed=st.is_completed,
                    mastery_score=mastery,
                    mastery_updated_at=st.mastery_updated_at,
                )
            )
        topics.append(
            TopicOut(
                id=topic.id,
                title=topic.title,
                order_index=topic.order_index,
                is_completed=topic.is_completed,
                subtopics=subs,
            )
        )

    return SubjectTreeOut(
        id=subject.id,
        name=subject.name,
        type=subject.type,
        status=subject.status,
        description=subject.description,
        syllabus_file_url=subject.syllabus_file_url,
        created_at=subject.created_at,
        topics=topics,
        progress={
            "total_subtopics": total_sub,
            "completed_subtopics": done_sub,
            "percent_complete": round(100 * done_sub / total_sub) if total_sub else 0,
            "avg_mastery": round(mastery_sum / total_sub) if total_sub else 0,
        },
    )


# --------------------------------------------------------------------------


@router.get("", response_model=List[SubjectListItem])
async def list_subjects(user: CurrentUser, db: DbSession):
    subjects = (
        await db.scalars(
            select(Subject)
            .where(Subject.user_id == user.id)
            .options(selectinload(Subject.topics).selectinload(Topic.subtopics))
            .order_by(Subject.created_at.desc())
        )
    ).all()

    items = []
    for s in subjects:
        subs = [st for t in s.topics for st in t.subtopics]
        masteries = [
            decayed_mastery(st.mastery_score, st.mastery_updated_at) for st in subs
        ]
        items.append(
            SubjectListItem(
                id=s.id,
                name=s.name,
                type=s.type,
                status=s.status,
                description=s.description,
                syllabus_file_url=s.syllabus_file_url,
                created_at=s.created_at,
                topic_count=len(s.topics),
                subtopic_count=len(subs),
                completed_subtopics=sum(1 for st in subs if st.is_completed),
                avg_mastery=round(sum(masteries) / len(masteries)) if masteries else 0,
            )
        )
    return items


@router.post("", response_model=SubjectTreeOut, status_code=201)
async def create_subject(payload: SubjectCreate, user: CurrentUser, db: DbSession):
    """Create a subject with a manually entered tree (PRD 7.1, 'no syllabus')."""
    subject = Subject(
        user_id=user.id,
        name=payload.name.strip(),
        type=payload.type,
        description=payload.description,
        status="active",
    )
    db.add(subject)
    _write_tree(subject, payload.topics)
    await db.flush()
    return await _reload_tree(db, subject.id, user.id)


@router.post("/upload", response_model=ParsedTreeOut, status_code=201)
async def upload_syllabus(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    name: str = Form(...),
    type: str = Form("non-coding"),
):
    """Upload a syllabus PDF; returns a draft tree for the user to confirm.

    The subject is saved with status='draft' and no tree is committed until
    POST /subjects/{id}/confirm (PRD open question 4).
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB"
        )

    file_url, _ = storage.save_upload(data, file.filename or "syllabus.pdf")
    text = syllabus.extract_text(data, file.filename or "syllabus.pdf")
    topics, confidence, detected_type = await syllabus.parse_syllabus(text, name)

    subject = Subject(
        user_id=user.id,
        name=name.strip(),
        type=type if type in ("coding", "non-coding") else detected_type,
        status="draft",
        syllabus_file_url=file_url,
        syllabus_text=text[:200_000] or None,
        extraction_confidence=confidence,
    )
    db.add(subject)
    await db.flush()

    needs_manual = not topics or confidence < 0.35
    if not text.strip():
        message = (
            "We couldn't read any text from that PDF — it looks like a scan. "
            "Add your topics manually and we'll take it from there."
        )
    elif needs_manual:
        message = (
            "We had trouble recognising a syllabus structure. Review the draft "
            "below, or add topics manually."
        )
    else:
        message = (
            f"Found {len(topics)} topics. Review and edit before confirming — "
            "nothing is saved to your tree until you confirm."
        )

    return ParsedTreeOut(
        subject_id=subject.id,
        status=subject.status,
        confidence=confidence,
        needs_manual_entry=needs_manual,
        message=message,
        topics=[TopicIn(**t) for t in topics],
    )


@router.post("/{subject_id}/confirm", response_model=SubjectTreeOut)
async def confirm_tree(
    subject_id: uuid.UUID, payload: TreeReplace, user: CurrentUser, db: DbSession
):
    """Commit the (possibly edited) tree and activate the subject."""
    subject = await load_subject(db, subject_id, user.id, with_tree=True)
    if not payload.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    _write_tree(subject, payload.topics)
    subject.status = "active"
    await db.flush()

    # index the syllabus text for topic-scoped retrieval (PRD 7.2)
    if subject.syllabus_text:
        try:
            await db.execute(
                sa_delete(ContentChunk).where(ContentChunk.subject_id == subject.id)
            )
            chunks = syllabus.chunk_text(subject.syllabus_text)
            await retrieval.index_chunks(
                db, subject_id=subject.id, chunks=chunks, source="syllabus"
            )
        except Exception as exc:  # noqa: BLE001 — indexing must never block saving
            logger.warning("Syllabus indexing failed for %s: %s", subject.id, exc)

    return await _reload_tree(db, subject.id, user.id)


@router.get("/{subject_id}/tree", response_model=SubjectTreeOut)
async def get_tree(subject_id: uuid.UUID, user: CurrentUser, db: DbSession):
    subject = await load_subject(db, subject_id, user.id, with_tree=True)
    return _serialize_tree(subject)


@router.put("/{subject_id}/tree", response_model=SubjectTreeOut)
async def replace_tree(
    subject_id: uuid.UUID, payload: TreeReplace, user: CurrentUser, db: DbSession
):
    """Bulk tree edit. Warning: replaces nodes, so progress on removed nodes is lost."""
    subject = await load_subject(db, subject_id, user.id, with_tree=True)
    _write_tree(subject, payload.topics)
    return await _reload_tree(db, subject.id, user.id)


@router.patch("/{subject_id}", response_model=SubjectTreeOut)
async def update_subject(
    subject_id: uuid.UUID, payload: SubjectUpdate, user: CurrentUser, db: DbSession
):
    subject = await load_subject(db, subject_id, user.id, with_tree=True)
    if payload.name is not None:
        subject.name = payload.name.strip()
    if payload.type is not None:
        subject.type = payload.type
    if payload.description is not None:
        subject.description = payload.description
    return await _reload_tree(db, subject.id, user.id)


@router.delete("/{subject_id}", status_code=204)
async def delete_subject(subject_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Deletion cascades to chats, assessments and chunks (PRD section 11)."""
    subject = await load_subject(db, subject_id, user.id)
    await db.delete(subject)


@router.post("/{subject_id}/topics", response_model=TopicOut, status_code=201)
async def add_topic(
    subject_id: uuid.UUID, payload: TopicIn, user: CurrentUser, db: DbSession
):
    subject = await load_subject(db, subject_id, user.id, with_tree=True)
    if len(subject.topics) >= settings.max_topics_per_subject:
        raise HTTPException(
            status_code=400,
            detail=f"Topic cap of {settings.max_topics_per_subject} reached",
        )

    next_index = (
        max((t.order_index for t in subject.topics), default=-1) + 1
    )
    topic = Topic(
        subject_id=subject.id,
        title=payload.title.strip()[:300],
        order_index=next_index,
        subtopics=[
            Subtopic(title=s.title.strip()[:300], order_index=j)
            for j, s in enumerate(payload.subtopics or [])
        ],
    )
    db.add(topic)
    await db.flush()

    topic = await db.scalar(
        select(Topic)
        .where(Topic.id == topic.id)
        .options(selectinload(Topic.subtopics))
        .execution_options(populate_existing=True)
    )
    return TopicOut(
        id=topic.id,
        title=topic.title,
        order_index=topic.order_index,
        is_completed=topic.is_completed,
        subtopics=[SubtopicOut.model_validate(s) for s in topic.subtopics],
    )

"""Topic / sub-topic checkbox tree operations (PRD 7.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Subject, Subtopic, Topic
from app.schemas import SubtopicIn, SubtopicOut, SubtopicPatch, TopicOut, TopicPatch
from app.services.assessment import decayed_mastery

router = APIRouter(tags=["topics"])


async def _load_topic(db, topic_id: uuid.UUID, user_id: uuid.UUID) -> Topic:
    """Always re-reads eagerly: after a flush, expired columns and collections
    would otherwise lazy-load outside the async greenlet context."""
    topic = await db.scalar(
        select(Topic)
        .join(Subject, Subject.id == Topic.subject_id)
        .where(Topic.id == topic_id, Subject.user_id == user_id)
        .options(selectinload(Topic.subtopics))
        .execution_options(populate_existing=True)
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


async def _load_subtopic(db, subtopic_id: uuid.UUID, user_id: uuid.UUID) -> Subtopic:
    subtopic = await db.scalar(
        select(Subtopic)
        .join(Topic, Topic.id == Subtopic.topic_id)
        .join(Subject, Subject.id == Topic.subject_id)
        .where(Subtopic.id == subtopic_id, Subject.user_id == user_id)
    )
    if subtopic is None:
        raise HTTPException(status_code=404, detail="Sub-topic not found")
    return subtopic


def _topic_out(topic: Topic) -> TopicOut:
    return TopicOut(
        id=topic.id,
        title=topic.title,
        order_index=topic.order_index,
        is_completed=topic.is_completed,
        subtopics=[
            SubtopicOut(
                id=s.id,
                title=s.title,
                order_index=s.order_index,
                is_completed=s.is_completed,
                mastery_score=decayed_mastery(s.mastery_score, s.mastery_updated_at),
                mastery_updated_at=s.mastery_updated_at,
            )
            for s in sorted(topic.subtopics, key=lambda s: s.order_index)
        ],
    )


@router.patch("/topics/{topic_id}", response_model=TopicOut)
async def patch_topic(
    topic_id: uuid.UUID, payload: TopicPatch, user: CurrentUser, db: DbSession
):
    """Rename, reorder, or tick a topic. Ticking cascades to its sub-topics."""
    topic = await _load_topic(db, topic_id, user.id)
    if payload.title is not None:
        topic.title = payload.title.strip()[:300]
    if payload.order_index is not None:
        topic.order_index = payload.order_index
    if payload.is_completed is not None:
        topic.is_completed = payload.is_completed
        for sub in topic.subtopics:
            sub.is_completed = payload.is_completed
    await db.flush()
    return _topic_out(await _load_topic(db, topic_id, user.id))


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(topic_id: uuid.UUID, user: CurrentUser, db: DbSession):
    topic = await _load_topic(db, topic_id, user.id)
    await db.delete(topic)


@router.post("/topics/{topic_id}/subtopics", response_model=SubtopicOut, status_code=201)
async def add_subtopic(
    topic_id: uuid.UUID, payload: SubtopicIn, user: CurrentUser, db: DbSession
):
    topic = await _load_topic(db, topic_id, user.id)
    subtopic = Subtopic(
        topic_id=topic.id,
        title=payload.title.strip()[:300],
        order_index=max((s.order_index for s in topic.subtopics), default=-1) + 1,
    )
    db.add(subtopic)
    await db.flush()
    await db.refresh(subtopic)
    return SubtopicOut.model_validate(subtopic)


@router.patch("/subtopics/{subtopic_id}", response_model=SubtopicOut)
async def patch_subtopic(
    subtopic_id: uuid.UUID, payload: SubtopicPatch, user: CurrentUser, db: DbSession
):
    """Mark a sub-topic complete — this is what feeds the assessment pool."""
    subtopic = await _load_subtopic(db, subtopic_id, user.id)
    if payload.title is not None:
        subtopic.title = payload.title.strip()[:300]
    if payload.order_index is not None:
        subtopic.order_index = payload.order_index
    if payload.is_completed is not None:
        subtopic.is_completed = payload.is_completed

    await db.flush()

    # roll the parent topic's checkbox up from its children
    topic = await _load_topic(db, subtopic.topic_id, user.id)
    topic.is_completed = bool(topic.subtopics) and all(
        s.is_completed for s in topic.subtopics
    )
    await db.flush()
    await db.refresh(subtopic)

    return SubtopicOut(
        id=subtopic.id,
        title=subtopic.title,
        order_index=subtopic.order_index,
        is_completed=subtopic.is_completed,
        mastery_score=decayed_mastery(
            subtopic.mastery_score, subtopic.mastery_updated_at
        ),
        mastery_updated_at=subtopic.mastery_updated_at,
    )


@router.delete("/subtopics/{subtopic_id}", status_code=204)
async def delete_subtopic(subtopic_id: uuid.UUID, user: CurrentUser, db: DbSession):
    subtopic = await _load_subtopic(db, subtopic_id, user.id)
    await db.delete(subtopic)

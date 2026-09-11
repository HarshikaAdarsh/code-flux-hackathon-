"""SQLAlchemy ORM models — implements the ER diagram in PRD section 8.

Additions beyond the PRD diagram:
  * ContentChunk  — pgvector store backing topic-scoped retrieval (PRD 7.2)
  * QuestionPool  — cached generated questions so pools are not regenerated
                    per attempt (PRD 11, cost control)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

EMBEDDING_DIM = 768  # gemini text-embedding-004


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    google_sub: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True
    )
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    pomodoro_minutes: Mapped[int] = mapped_column(Integer, default=25)

    subjects: Mapped[List["Subject"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------
# Subject → Topic → Subtopic tree
# --------------------------------------------------------------------------


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # "coding" | "non-coding"
    type: Mapped[str] = mapped_column(String(20), default="non-coding")
    # "draft" until the user confirms an AI-generated tree (PRD open q4)
    status: Mapped[str] = mapped_column(String(20), default="active")
    description: Mapped[Optional[str]] = mapped_column(Text)
    syllabus_file_url: Mapped[Optional[str]] = mapped_column(String(500))
    syllabus_text: Mapped[Optional[str]] = mapped_column(Text)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)

    user: Mapped["User"] = relationship(back_populates="subjects")
    topics: Mapped[List["Topic"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="Topic.order_index",
    )


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped["Subject"] = relationship(back_populates="topics")
    subtopics: Mapped[List["Subtopic"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        order_by="Subtopic.order_index",
    )


class Subtopic(Base, TimestampMixin):
    __tablename__ = "subtopics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 0-100, updated after every answered question (PRD 7.3)
    mastery_score: Mapped[int] = mapped_column(Integer, default=0)
    # anchor for time decay (PRD open question 2)
    mastery_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    topic: Mapped["Topic"] = relationship(back_populates="subtopics")
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        back_populates="subtopic", cascade="all, delete-orphan"
    )
    attempts: Mapped[List["AssessmentAttempt"]] = relationship(
        back_populates="subtopic", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------
# Teaching chat
# --------------------------------------------------------------------------


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subtopic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("subtopics.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(10), default="text")  # text|voice
    language: Mapped[str] = mapped_column(String(8), default="en")
    title: Mapped[Optional[str]] = mapped_column(String(300))
    # [{role, content, provider?, created_at}]
    messages: Mapped[list] = mapped_column(JSONB, default=list)

    subtopic: Mapped[Optional["Subtopic"]] = relationship(
        back_populates="chat_sessions"
    )


class ContentChunk(Base):
    """Embedded syllabus / lesson text used as retrieval context (PRD 7.2)."""

    __tablename__ = "content_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    subtopic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("subtopics.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(30), default="syllabus")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------


class QuestionPool(Base):
    """Pre-generated question bank per subtopic+difficulty, reused across
    attempts so a new attempt does not burn LLM quota (PRD 11)."""

    __tablename__ = "question_pools"
    __table_args__ = (
        UniqueConstraint("subtopic_id", "difficulty", name="uq_pool_subtopic_diff"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subtopics.id", ondelete="CASCADE"), index=True
    )
    difficulty: Mapped[str] = mapped_column(String(10))  # basic|medium|hard
    kind: Mapped[str] = mapped_column(String(10), default="theory")  # theory|coding
    # theory: [{id, question, options?, answer, explanation}]
    # coding: [{id, title, prompt, starter_code, tests:[{input, expected}], solution}]
    questions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AssessmentAttempt(Base, TimestampMixin):
    __tablename__ = "assessment_attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subtopic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subtopics.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10), default="theory")
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    language: Mapped[str] = mapped_column(String(8), default="en")

    current_difficulty: Mapped[str] = mapped_column(String(10), default="basic")
    correct_streak: Mapped[int] = mapped_column(Integer, default=0)
    incorrect_streak: Mapped[int] = mapped_column(Integer, default=0)
    questions_answered: Mapped[int] = mapped_column(Integer, default=0)
    max_questions: Mapped[int] = mapped_column(Integer, default=10)
    highest_difficulty_reached: Mapped[str] = mapped_column(
        String(10), default="basic"
    )

    # the question currently shown to the user (server-authoritative)
    active_question: Mapped[Optional[dict]] = mapped_column(JSONB)
    # ids already served this attempt, to avoid repeats
    served_question_ids: Mapped[list] = mapped_column(JSONB, default=list)

    final_mastery_score: Mapped[Optional[int]] = mapped_column(Integer)
    summary: Mapped[Optional[dict]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    subtopic: Mapped["Subtopic"] = relationship(back_populates="attempts")
    responses: Mapped[List["QuestionResponse"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="QuestionResponse.created_at",
    )


class QuestionResponse(Base):
    __tablename__ = "question_responses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[Optional[str]] = mapped_column(String(64))
    question_text: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10), default="theory")
    user_answer: Mapped[Optional[str]] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_feedback: Mapped[Optional[str]] = mapped_column(Text)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    needed_solution: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    attempt: Mapped["AssessmentAttempt"] = relationship(
        back_populates="responses"
    )


# --------------------------------------------------------------------------
# Focus sessions
# --------------------------------------------------------------------------


class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), index=True
    )
    subtopic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("subtopics.id", ondelete="SET NULL")
    )
    planned_minutes: Mapped[int] = mapped_column(Integer, default=25)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )


Index("ix_pomodoro_user_started", PomodoroSession.user_id, PomodoroSession.started_at)

"""Initial schema — PRD section 8 data model plus pgvector retrieval store.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _timestamps() -> list:
    return [
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("google_sub", sa.String(64), unique=True),
        sa.Column("preferred_language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("pomodoro_minutes", sa.Integer, nullable=False, server_default="25"),
        *_timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="non-coding"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("description", sa.Text),
        sa.Column("syllabus_file_url", sa.String(500)),
        sa.Column("syllabus_text", sa.Text),
        sa.Column("extraction_confidence", sa.Float),
        *_timestamps(),
    )
    op.create_index("ix_subjects_user_id", "subjects", ["user_id"])

    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_completed", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamps(),
    )
    op.create_index("ix_topics_subject_id", "topics", ["subject_id"])

    op.create_table(
        "subtopics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_completed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("mastery_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mastery_updated_at", TS),
        *_timestamps(),
    )
    op.create_index("ix_subtopics_topic_id", "subtopics", ["topic_id"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
        ),
        sa.Column("mode", sa.String(10), nullable=False, server_default="text"),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("title", sa.String(300)),
        sa.Column(
            "messages",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_subtopic_id", "chat_sessions", ["subtopic_id"])
    op.create_index("ix_chat_sessions_subject_id", "chat_sessions", ["subject_id"])

    op.create_table(
        "content_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="CASCADE"),
        ),
        sa.Column("source", sa.String(30), nullable=False, server_default="syllabus"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768)),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_content_chunks_subject_id", "content_chunks", ["subject_id"])
    op.create_index("ix_content_chunks_subtopic_id", "content_chunks", ["subtopic_id"])
    # cosine ANN index for topic-scoped retrieval
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding ON content_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "question_pools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="theory"),
        sa.Column(
            "questions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.UniqueConstraint("subtopic_id", "difficulty", name="uq_pool_subtopic_diff"),
    )
    op.create_index("ix_question_pools_subtopic_id", "question_pools", ["subtopic_id"])

    op.create_table(
        "assessment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(10), nullable=False, server_default="theory"),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column(
            "current_difficulty", sa.String(10), nullable=False, server_default="basic"
        ),
        sa.Column("correct_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("incorrect_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("questions_answered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_questions", sa.Integer, nullable=False, server_default="10"),
        sa.Column(
            "highest_difficulty_reached",
            sa.String(10),
            nullable=False,
            server_default="basic",
        ),
        sa.Column("active_question", postgresql.JSONB),
        sa.Column(
            "served_question_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("final_mastery_score", sa.Integer),
        sa.Column("summary", postgresql.JSONB),
        sa.Column("started_at", TS, server_default=NOW, nullable=False),
        sa.Column("completed_at", TS),
        *_timestamps(),
    )
    op.create_index(
        "ix_assessment_attempts_user_id", "assessment_attempts", ["user_id"]
    )
    op.create_index(
        "ix_assessment_attempts_subtopic_id", "assessment_attempts", ["subtopic_id"]
    )

    op.create_table(
        "question_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_id", sa.String(64)),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="theory"),
        sa.Column("user_answer", sa.Text),
        sa.Column("is_correct", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ai_feedback", sa.Text),
        sa.Column("hints_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "needed_solution", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("execution_result", postgresql.JSONB),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_question_responses_attempt_id", "question_responses", ["attempt_id"]
    )

    op.create_table(
        "pomodoro_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subjects.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "subtopic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subtopics.id", ondelete="SET NULL"),
        ),
        sa.Column("planned_minutes", sa.Integer, nullable=False, server_default="25"),
        sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("started_at", TS, server_default=NOW, nullable=False),
        sa.Column("ended_at", TS),
    )
    op.create_index("ix_pomodoro_sessions_user_id", "pomodoro_sessions", ["user_id"])
    op.create_index(
        "ix_pomodoro_sessions_subject_id", "pomodoro_sessions", ["subject_id"]
    )
    op.create_index(
        "ix_pomodoro_user_started", "pomodoro_sessions", ["user_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_table("pomodoro_sessions")
    op.drop_table("question_responses")
    op.drop_table("assessment_attempts")
    op.drop_table("question_pools")
    op.drop_table("content_chunks")
    op.drop_table("chat_sessions")
    op.drop_table("subtopics")
    op.drop_table("topics")
    op.drop_table("subjects")
    op.drop_table("users")

"""Pomodoro focus sessions (PRD 7.8). Logged now, charted in Phase 2."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.deps import CurrentUser, DbSession
from app.models import PomodoroSession, Subject
from app.schemas import PomodoroOut, PomodoroStartRequest, PomodoroStatsOut

router = APIRouter(prefix="/pomodoro", tags=["pomodoro"])


def _elapsed_minutes(started: datetime) -> int:
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds() // 60))


async def _load_session(db, session_id: uuid.UUID, user_id: uuid.UUID) -> PomodoroSession:
    session = await db.scalar(
        select(PomodoroSession).where(
            PomodoroSession.id == session_id, PomodoroSession.user_id == user_id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Focus session not found")
    return session


@router.post("/start", response_model=PomodoroOut, status_code=201)
async def start(payload: PomodoroStartRequest, user: CurrentUser, db: DbSession):
    if payload.subject_id:
        owned = await db.scalar(
            select(Subject.id).where(
                Subject.id == payload.subject_id, Subject.user_id == user.id
            )
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="Subject not found")

    # only one live session at a time — auto-close any stale one
    active = await db.scalar(
        select(PomodoroSession).where(
            PomodoroSession.user_id == user.id,
            PomodoroSession.status.in_(("active", "paused")),
        )
    )
    if active is not None:
        active.status = "abandoned"
        active.ended_at = datetime.now(timezone.utc)
        active.duration_minutes = _elapsed_minutes(active.started_at)

    session = PomodoroSession(
        user_id=user.id,
        subject_id=payload.subject_id,
        subtopic_id=payload.subtopic_id,
        planned_minutes=payload.planned_minutes,
        status="active",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.post("/{session_id}/pause", response_model=PomodoroOut)
async def pause(session_id: uuid.UUID, user: CurrentUser, db: DbSession):
    session = await _load_session(db, session_id, user.id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session is not running")
    session.status = "paused"
    session.duration_minutes = _elapsed_minutes(session.started_at)
    await db.flush()
    await db.refresh(session)
    return session


@router.post("/{session_id}/resume", response_model=PomodoroOut)
async def resume(session_id: uuid.UUID, user: CurrentUser, db: DbSession):
    session = await _load_session(db, session_id, user.id)
    if session.status != "paused":
        raise HTTPException(status_code=409, detail="Session is not paused")
    session.status = "active"
    await db.flush()
    await db.refresh(session)
    return session


@router.post("/{session_id}/stop", response_model=PomodoroOut)
async def stop(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    completed: bool = True,
    duration_minutes: Optional[int] = None,
):
    """Stop a session. Pass the client's tracked duration for accuracy."""
    session = await _load_session(db, session_id, user.id)
    if session.ended_at is not None:
        return session
    session.status = "completed" if completed else "abandoned"
    session.ended_at = datetime.now(timezone.utc)
    session.duration_minutes = (
        duration_minutes
        if duration_minutes is not None
        else _elapsed_minutes(session.started_at)
    )
    await db.flush()
    await db.refresh(session)
    return session


@router.get("/active", response_model=Optional[PomodoroOut])
async def active_session(user: CurrentUser, db: DbSession):
    return await db.scalar(
        select(PomodoroSession)
        .where(
            PomodoroSession.user_id == user.id,
            PomodoroSession.status.in_(("active", "paused")),
        )
        .order_by(PomodoroSession.started_at.desc())
    )


@router.get("/sessions", response_model=List[PomodoroOut])
async def list_sessions(user: CurrentUser, db: DbSession, limit: int = 50):
    return (
        await db.scalars(
            select(PomodoroSession)
            .where(PomodoroSession.user_id == user.id)
            .order_by(PomodoroSession.started_at.desc())
            .limit(min(limit, 200))
        )
    ).all()


@router.get("/stats", response_model=PomodoroStatsOut)
async def stats(user: CurrentUser, db: DbSession, days: int = 30):
    """Aggregates that Phase 2's heatmap will render directly."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))

    totals = (
        await db.execute(
            select(
                func.count(PomodoroSession.id),
                func.coalesce(func.sum(PomodoroSession.duration_minutes), 0),
            ).where(PomodoroSession.user_id == user.id)
        )
    ).first()

    week_minutes = await db.scalar(
        select(func.coalesce(func.sum(PomodoroSession.duration_minutes), 0)).where(
            PomodoroSession.user_id == user.id,
            PomodoroSession.started_at >= datetime.now(timezone.utc) - timedelta(days=7),
        )
    )

    by_subject = (
        await db.execute(
            select(
                Subject.name,
                func.coalesce(func.sum(PomodoroSession.duration_minutes), 0),
                func.count(PomodoroSession.id),
            )
            .join(Subject, Subject.id == PomodoroSession.subject_id)
            .where(PomodoroSession.user_id == user.id)
            .group_by(Subject.name)
            .order_by(func.sum(PomodoroSession.duration_minutes).desc())
        )
    ).all()

    daily = (
        await db.execute(
            select(
                func.date(PomodoroSession.started_at),
                func.coalesce(func.sum(PomodoroSession.duration_minutes), 0),
                func.count(PomodoroSession.id),
            )
            .where(
                PomodoroSession.user_id == user.id,
                PomodoroSession.started_at >= since,
            )
            .group_by(func.date(PomodoroSession.started_at))
            .order_by(func.date(PomodoroSession.started_at))
        )
    ).all()

    return PomodoroStatsOut(
        total_sessions=totals[0] or 0,
        total_minutes=int(totals[1] or 0),
        minutes_last_7_days=int(week_minutes or 0),
        by_subject=[
            {"subject": name, "minutes": int(minutes), "sessions": count}
            for name, minutes, count in by_subject
        ],
        daily=[
            {"date": str(day), "minutes": int(minutes), "sessions": count}
            for day, minutes, count in daily
        ],
    )

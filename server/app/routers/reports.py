"""Strength / weakness reporting (PRD 7.6)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from sqlalchemy import Integer, cast, func, select

from app.deps import CurrentUser, DbSession
from app.models import (
    AssessmentAttempt,
    PomodoroSession,
    QuestionResponse,
    Subject,
    Subtopic,
    Topic,
)
from app.schemas import SubjectReportOut, SubtopicReport
from app.services import assessment, llm, prompts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])

DIFFICULTY_RANK = {"basic": 0, "medium": 1, "hard": 2}


@router.get("/{subject_id}", response_model=SubjectReportOut)
async def subject_report(
    subject_id: uuid.UUID, user: CurrentUser, db: DbSession, ai_summary: bool = True
):
    subject = await db.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.user_id == user.id)
    )
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    rows = (
        await db.execute(
            select(Subtopic, Topic.title)
            .join(Topic, Topic.id == Subtopic.topic_id)
            .where(Topic.subject_id == subject_id)
            .order_by(Topic.order_index, Subtopic.order_index)
        )
    ).all()

    # aggregate every answered question per sub-topic (PRD 7.6 step 1-3)
    stats = {
        st_id: {
            "answered": answered,
            "correct": correct or 0,
            "hints": hints or 0,
            "attempts": attempts,
        }
        for st_id, answered, correct, hints, attempts in (
            await db.execute(
                select(
                    AssessmentAttempt.subtopic_id,
                    func.count(QuestionResponse.id),
                    func.sum(cast(QuestionResponse.is_correct, Integer)),
                    func.sum(QuestionResponse.hints_used),
                    func.count(func.distinct(AssessmentAttempt.id)),
                )
                .join(
                    QuestionResponse,
                    QuestionResponse.attempt_id == AssessmentAttempt.id,
                )
                .where(AssessmentAttempt.user_id == user.id)
                .group_by(AssessmentAttempt.subtopic_id)
            )
        ).all()
    }

    reached = {
        st_id: difficulty
        for st_id, difficulty in (
            await db.execute(
                select(
                    AssessmentAttempt.subtopic_id,
                    func.max(AssessmentAttempt.highest_difficulty_reached),
                )
                .where(AssessmentAttempt.user_id == user.id)
                .group_by(AssessmentAttempt.subtopic_id)
            )
        ).all()
    }

    buckets: Dict[str, List[SubtopicReport]] = {
        "strength": [],
        "weakness": [],
        "needs_practice": [],
        "untested": [],
    }
    mastery_values: List[int] = []

    for subtopic, topic_title in rows:
        mastery = assessment.decayed_mastery(
            subtopic.mastery_score, subtopic.mastery_updated_at
        )
        stat = stats.get(subtopic.id)
        highest = reached.get(subtopic.id, "basic")

        if not stat or not stat["answered"]:
            classification = "untested"
            accuracy = 0.0
            attempts = hints = 0
        else:
            accuracy = stat["correct"] / stat["answered"]
            attempts = stat["attempts"]
            hints = stat["hints"]
            classification = assessment.classify(accuracy, highest, mastery)
            mastery_values.append(mastery)

        buckets[classification].append(
            SubtopicReport(
                subtopic_id=subtopic.id,
                topic=topic_title,
                subtopic=subtopic.title,
                attempts=attempts,
                accuracy=round(accuracy, 3),
                mastery_score=mastery,
                highest_difficulty_reached=highest,
                hints_used=hints,
                classification=classification,
            )
        )

    buckets["weakness"].sort(key=lambda r: r.mastery_score)
    buckets["strength"].sort(key=lambda r: -r.mastery_score)

    since = datetime.now(timezone.utc) - timedelta(days=7)
    study_minutes = await db.scalar(
        select(func.coalesce(func.sum(PomodoroSession.duration_minutes), 0)).where(
            PomodoroSession.user_id == user.id,
            PomodoroSession.subject_id == subject_id,
            PomodoroSession.started_at >= since,
        )
    )

    # deterministic recommendation first, then let the LLM enrich it
    recommendation = None
    if buckets["weakness"]:
        recommendation = (
            f"Start with {buckets['weakness'][0].subtopic} — it's your weakest "
            "area right now."
        )
    elif buckets["untested"]:
        recommendation = (
            f"Test yourself on {buckets['untested'][0].subtopic} next to find "
            "your gaps."
        )
    elif buckets["needs_practice"]:
        recommendation = f"Practise {buckets['needs_practice'][0].subtopic} once more."
    else:
        recommendation = "You're on top of this subject. Keep revising to hold it."

    if ai_summary and (buckets["weakness"] or buckets["needs_practice"]):
        payload = [
            r.model_dump(mode="json")
            for group in ("strength", "weakness", "needs_practice")
            for r in buckets[group][:6]
        ]
        try:
            data = await llm.complete_json(
                prompts.build_report_messages(
                    subject=subject.name,
                    rows=payload,
                    language=user.preferred_language,
                ),
                lane_name="background",
                max_tokens=800,
            )
            if data.get("next_action"):
                recommendation = data["next_action"]
                if data.get("study_plan"):
                    recommendation += "\n\n" + "\n".join(
                        f"{i + 1}. {s}" for i, s in enumerate(data["study_plan"][:3])
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI report summary unavailable: %s", exc)

    total = sum(len(v) for v in buckets.values())
    return SubjectReportOut(
        subject_id=subject.id,
        subject=subject.name,
        overall_mastery=(
            round(sum(mastery_values) / len(mastery_values)) if mastery_values else 0
        ),
        tested_subtopics=total - len(buckets["untested"]),
        total_subtopics=total,
        strengths=buckets["strength"],
        weaknesses=buckets["weakness"],
        needs_practice=buckets["needs_practice"],
        untested=buckets["untested"],
        next_recommendation=recommendation,
        study_minutes_7d=int(study_minutes or 0),
    )

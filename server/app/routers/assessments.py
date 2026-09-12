"""Adaptive assessments — theory ladder and coding sandbox (PRD 7.3, 7.4)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import (
    AssessmentAttempt,
    QuestionResponse,
    Subject,
    Subtopic,
    Topic,
    User,
)
from app.schemas import (
    AnswerRequest,
    AnswerResponse,
    AssessmentStartRequest,
    AssessmentStateOut,
    AttemptSummaryOut,
    CodeSubmitRequest,
    CodeSubmitResponse,
    HintRequest,
    HintResponse,
    QuestionOut,
    TestCaseResult,
)
from app.services import assessment, llm, prompts, sandbox, verifier
from app.services.voice import normalise_language

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assessments", tags=["assessments"])


# --------------------------------------------------------------------------
# Loading helpers
# --------------------------------------------------------------------------


async def _load_scope(
    db, subtopic_id: uuid.UUID, user_id: uuid.UUID
) -> Tuple[Subtopic, Topic, Subject]:
    row = (
        await db.execute(
            select(Subtopic, Topic, Subject)
            .join(Topic, Topic.id == Subtopic.topic_id)
            .join(Subject, Subject.id == Topic.subject_id)
            .where(Subtopic.id == subtopic_id, Subject.user_id == user_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sub-topic not found")
    return row


async def _load_attempt(
    db, attempt_id: uuid.UUID, user_id: uuid.UUID, *, with_responses: bool = False
) -> AssessmentAttempt:
    stmt = select(AssessmentAttempt).where(
        AssessmentAttempt.id == attempt_id, AssessmentAttempt.user_id == user_id
    )
    if with_responses:
        stmt = stmt.options(selectinload(AssessmentAttempt.responses))
    attempt = await db.scalar(stmt)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    return attempt


def _state(
    attempt: AssessmentAttempt,
    subtopic: Subtopic,
    *,
    feedback: Optional[str] = None,
) -> AssessmentStateOut:
    question = None
    if attempt.status == "in_progress" and attempt.active_question:
        question = QuestionOut(**assessment.public_question(attempt.active_question))
    return AssessmentStateOut(
        attempt_id=attempt.id,
        status=attempt.status,
        kind=attempt.kind,
        current_difficulty=attempt.current_difficulty,
        questions_answered=attempt.questions_answered,
        max_questions=attempt.max_questions,
        mastery_score=subtopic.mastery_score,
        question=question,
        last_feedback=feedback,
        finished=attempt.status != "in_progress",
    )


# --------------------------------------------------------------------------
# Attempt progression
# --------------------------------------------------------------------------


async def _load_question(
    db,
    attempt: AssessmentAttempt,
    subtopic: Subtopic,
    topic: Topic,
    subject: Subject,
) -> Optional[Dict[str, Any]]:
    """Fetch the next unseen question at the attempt's current difficulty."""
    pool = await assessment.ensure_pool(
        db,
        subtopic=subtopic,
        topic=topic,
        subject=subject,
        difficulty=attempt.current_difficulty,
        kind=attempt.kind,
        language=attempt.language,
        context=(subject.syllabus_text or "")[:3000] or None,
    )
    if not pool:
        return None
    question = assessment.pick_question(pool, list(attempt.served_question_ids or []))
    if question is None:
        return None
    attempt.active_question = dict(question)
    attempt.served_question_ids = list(attempt.served_question_ids or []) + [
        question["id"]
    ]
    return question


async def _finish(db, attempt: AssessmentAttempt, subtopic: Subtopic) -> None:
    attempt.status = "completed"
    attempt.completed_at = datetime.now(timezone.utc)
    attempt.active_question = None
    attempt.final_mastery_score = subtopic.mastery_score

    responses = (
        await db.scalars(
            select(QuestionResponse)
            .where(QuestionResponse.attempt_id == attempt.id)
            .order_by(QuestionResponse.created_at)
        )
    ).all()
    attempt.summary = assessment.build_summary(
        attempt, list(responses), subtopic.title, subtopic.mastery_score
    )
    await db.flush()


async def _record_and_advance(
    db,
    *,
    attempt: AssessmentAttempt,
    subtopic: Subtopic,
    topic: Topic,
    subject: Subject,
    question: Dict[str, Any],
    user_answer: str,
    is_correct: bool,
    feedback: str,
    hints_used: int,
    needed_solution: bool = False,
    execution_result: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist the response, move the ladder, update mastery, load next."""
    db.add(
        QuestionResponse(
            attempt_id=attempt.id,
            question_id=question.get("id"),
            question_text=question.get("question", "")[:4000],
            difficulty=question.get("difficulty", attempt.current_difficulty),
            kind=attempt.kind,
            user_answer=(user_answer or "")[:8000],
            is_correct=is_correct,
            ai_feedback=(feedback or "")[:6000],
            hints_used=hints_used,
            needed_solution=needed_solution,
            execution_result=execution_result,
        )
    )

    # rolling mastery, updated after every question (PRD 7.3)
    subtopic.mastery_score = assessment.apply_mastery_delta(
        assessment.decayed_mastery(subtopic.mastery_score, subtopic.mastery_updated_at),
        question.get("difficulty", attempt.current_difficulty),
        is_correct,
        hints_used,
    )
    subtopic.mastery_updated_at = datetime.now(timezone.utc)

    attempt.questions_answered += 1
    if is_correct:
        attempt.correct_streak += 1
        attempt.incorrect_streak = 0
    else:
        attempt.incorrect_streak += 1
        attempt.correct_streak = 0

    next_difficulty, correct_streak, incorrect_streak = assessment.step_difficulty(
        attempt.current_difficulty, attempt.correct_streak, attempt.incorrect_streak
    )
    attempt.current_difficulty = next_difficulty
    attempt.correct_streak = correct_streak
    attempt.incorrect_streak = incorrect_streak

    if assessment.LADDER.index(next_difficulty) > assessment.LADDER.index(
        attempt.highest_difficulty_reached
    ):
        attempt.highest_difficulty_reached = next_difficulty

    await db.flush()

    if assessment.should_stop(attempt, subtopic.mastery_score):
        await _finish(db, attempt, subtopic)
        return

    if await _load_question(db, attempt, subtopic, topic, subject) is None:
        await _finish(db, attempt, subtopic)
    await db.flush()


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.post("/start", response_model=AssessmentStateOut, status_code=201)
async def start_assessment(
    payload: AssessmentStartRequest, user: CurrentUser, db: DbSession
):
    """Begin an adaptive assessment on a completed sub-topic."""
    subtopic, topic, subject = await _load_scope(db, payload.subtopic_id, user.id)
    if not subtopic.is_completed:
        raise HTTPException(
            status_code=400,
            detail="Study and tick this sub-topic before testing yourself on it",
        )

    # resume an unfinished attempt rather than burning quota on a new pool
    existing = await db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.user_id == user.id,
            AssessmentAttempt.subtopic_id == subtopic.id,
            AssessmentAttempt.status == "in_progress",
        )
    )
    if existing is not None and existing.active_question:
        return _state(existing, subtopic)

    attempt = AssessmentAttempt(
        user_id=user.id,
        subtopic_id=subtopic.id,
        kind="coding" if subject.type == "coding" else "theory",
        language=normalise_language(payload.language, user.preferred_language),
        max_questions=payload.max_questions or settings.assessment_default_length,
        current_difficulty="basic",
        served_question_ids=[],
    )
    db.add(attempt)
    await db.flush()

    if await _load_question(db, attempt, subtopic, topic, subject) is None:
        await db.delete(attempt)
        # Either the AI service is unavailable, or both generation attempts
        # failed the quality gate. In the second case we deliberately store
        # nothing: a wrong answer key would corrupt the student's mastery
        # score, so a disclaimer is the honest outcome (Track 2 fallback).
        raise HTTPException(
            status_code=503,
            detail=verifier.fallback_message(subtopic.title),
        )

    await db.flush()
    return _state(attempt, subtopic)


@router.get("/{attempt_id}", response_model=AssessmentStateOut)
async def get_assessment(attempt_id: uuid.UUID, user: CurrentUser, db: DbSession):
    attempt = await _load_attempt(db, attempt_id, user.id)
    subtopic, _, _ = await _load_scope(db, attempt.subtopic_id, user.id)
    return _state(attempt, subtopic)


@router.post("/{attempt_id}/answer", response_model=AnswerResponse)
async def submit_answer(
    attempt_id: uuid.UUID, payload: AnswerRequest, user: CurrentUser, db: DbSession
):
    """Submit a theory answer (PRD 7.3)."""
    attempt = await _load_attempt(db, attempt_id, user.id)
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail="This assessment is already finished")
    if attempt.kind == "coding":
        raise HTTPException(
            status_code=400, detail="This is a coding assessment — use /submit-code"
        )
    question = attempt.active_question
    if not question:
        raise HTTPException(status_code=409, detail="No active question")

    subtopic, topic, subject = await _load_scope(db, attempt.subtopic_id, user.id)

    is_correct, grader_note = await assessment.grade_theory(
        question, payload.answer, attempt.language
    )
    feedback = grader_note or await assessment.explain_answer(
        question, payload.answer, is_correct, attempt.language
    )

    await _record_and_advance(
        db,
        attempt=attempt,
        subtopic=subtopic,
        topic=topic,
        subject=subject,
        question=question,
        user_answer=payload.answer,
        is_correct=is_correct,
        feedback=feedback,
        hints_used=max(0, payload.hints_used),
    )

    return AnswerResponse(
        is_correct=is_correct,
        correct_answer=None if is_correct else question.get("answer"),
        feedback=feedback,
        state=_state(attempt, subtopic, feedback=feedback),
    )


@router.post("/{attempt_id}/submit-code", response_model=CodeSubmitResponse)
async def submit_code(
    attempt_id: uuid.UUID, payload: CodeSubmitRequest, user: CurrentUser, db: DbSession
):
    """Submit code: run in the sandbox, then teach from the error (PRD 7.4).

    A failing submission does NOT consume the question — the student keeps
    iterating with hints until they pass or explicitly give up.
    """
    attempt = await _load_attempt(db, attempt_id, user.id)
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail="This assessment is already finished")
    if attempt.kind != "coding":
        raise HTTPException(
            status_code=400, detail="This is a theory assessment — use /answer"
        )
    question = attempt.active_question
    if not question:
        raise HTTPException(status_code=409, detail="No active question")

    subtopic, topic, subject = await _load_scope(db, attempt.subtopic_id, user.id)
    failed_attempts = int(question.get("failed_attempts", 0))
    problem_text = question.get("question", "")

    # --- student gave up: reveal the solution, record as 'needed help' ---
    if payload.give_up:
        # Track 2: an official solution is the one thing a stuck student will
        # take entirely on trust, so it is verified before it is shown.
        async def make_walkthrough(critique):
            messages = prompts.build_solution_messages(
                problem=problem_text,
                solution=question.get("solution", ""),
                code=payload.code,
                language=attempt.language,
            )
            if critique:
                messages.append({"role": "user", "content": critique})
            result = await llm.complete(
                messages, lane_name="interactive", max_tokens=1024
            )
            return result.text if result.provider != "none" else None

        text, _verdict = await verifier.generate_verified(
            kind="a worked solution walkthrough shown to a student who gave up",
            generate=make_walkthrough,
            subject=subject.name,
            topic=topic.title,
            subtopic=subtopic.title,
        )
        walkthrough = SimpleNamespace(
            text=text or verifier.fallback_message(subtopic.title)
        )
        await _record_and_advance(
            db,
            attempt=attempt,
            subtopic=subtopic,
            topic=topic,
            subject=subject,
            question=question,
            user_answer=payload.code,
            is_correct=False,
            feedback=walkthrough.text,
            hints_used=failed_attempts + payload.hints_used,
            needed_solution=True,
        )
        return CodeSubmitResponse(
            attempt_id=attempt.id,
            passed=False,
            tests=[],
            feedback=walkthrough.text,
            solution=question.get("solution"),
            state=_state(attempt, subtopic, feedback=walkthrough.text),
        )

    # --- run the submission ---
    execution = await sandbox.run_python(payload.code, question.get("tests") or [])
    tests = [
        TestCaseResult(
            name=t.get("name", ""),
            passed=bool(t.get("passed")),
            input=t.get("input"),
            expected=t.get("expected"),
            actual=t.get("actual"),
            error=t.get("error"),
        )
        for t in execution.get("tests", [])
    ]

    if execution.get("passed"):
        # even on a pass, the LLM reviews style/approach (PRD open question 3)
        feedback = "All tests passed."
        try:
            review = await llm.complete_json(
                prompts.build_code_review_messages(
                    problem=problem_text, code=payload.code, language=attempt.language
                ),
                lane_name="interactive",
                max_tokens=800,
            )
            feedback = review.get("feedback") or feedback
            if review.get("suggestions"):
                feedback += "\n\n**Suggestions:**\n" + "\n".join(
                    f"- {s}" for s in review["suggestions"][:3]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Code style review failed: %s", exc)

        await _record_and_advance(
            db,
            attempt=attempt,
            subtopic=subtopic,
            topic=topic,
            subject=subject,
            question=question,
            user_answer=payload.code,
            is_correct=True,
            feedback=feedback,
            hints_used=failed_attempts + payload.hints_used,
            execution_result={
                "runner": execution.get("runner"),
                "runtime_ms": execution.get("runtime_ms"),
                "tests_passed": len(tests),
            },
        )
        return CodeSubmitResponse(
            attempt_id=attempt.id,
            passed=True,
            tests=tests,
            stdout=execution.get("stdout", ""),
            stderr=execution.get("stderr", ""),
            runtime_ms=execution.get("runtime_ms", 0),
            feedback=feedback,
            state=_state(attempt, subtopic, feedback=feedback),
        )

    # --- failed: teach from the error, keep the question open for a retry ---
    failures = [t for t in execution.get("tests", []) if not t.get("passed")]
    diagnosis = "Your code didn't pass all the tests yet."
    hint = None
    try:
        analysis = await llm.complete_json(
            prompts.build_code_error_messages(
                problem=problem_text,
                code=payload.code,
                failures=failures,
                stderr=execution.get("stderr", "") or execution.get("error", "") or "",
                language=attempt.language,
            ),
            lane_name="interactive",
            max_tokens=900,
        )
        diagnosis = analysis.get("diagnosis") or diagnosis
        hint = analysis.get("hint")
        if analysis.get("concept_to_review"):
            diagnosis += f"\n\n**Review:** {analysis['concept_to_review']}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error analysis failed: %s", exc)
        if execution.get("error"):
            diagnosis += f"\n\n```\n{str(execution['error'])[:800]}\n```"

    question = dict(question)
    question["failed_attempts"] = failed_attempts + 1
    attempt.active_question = question
    await db.flush()

    return CodeSubmitResponse(
        attempt_id=attempt.id,
        passed=False,
        tests=tests,
        stdout=execution.get("stdout", ""),
        stderr=execution.get("stderr", ""),
        runtime_ms=execution.get("runtime_ms", 0),
        feedback=diagnosis,
        hint=hint,
        state=_state(attempt, subtopic, feedback=diagnosis),
    )


@router.post("/{attempt_id}/hint", response_model=HintResponse)
async def get_hint(
    attempt_id: uuid.UUID, payload: HintRequest, user: CurrentUser, db: DbSession
):
    """A guided nudge. Using hints lowers the mastery gained on this question."""
    attempt = await _load_attempt(db, attempt_id, user.id)
    if attempt.status != "in_progress" or not attempt.active_question:
        raise HTTPException(status_code=409, detail="No active question")

    question = dict(attempt.active_question)
    result = await llm.complete(
        prompts.build_hint_messages(
            question=question.get("question", ""),
            code=payload.code,
            language=attempt.language,
        ),
        lane_name="interactive",
        max_tokens=300,
    )
    used = int(question.get("hints_used", 0)) + 1
    question["hints_used"] = used
    attempt.active_question = question
    await db.flush()

    return HintResponse(hint=result.text, hints_used=used)


@router.post("/{attempt_id}/finish", response_model=AttemptSummaryOut)
async def finish_assessment(attempt_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """End an attempt early and score what was answered."""
    attempt = await _load_attempt(db, attempt_id, user.id)
    subtopic, _, _ = await _load_scope(db, attempt.subtopic_id, user.id)
    if attempt.status == "in_progress":
        await _finish(db, attempt, subtopic)
    return AttemptSummaryOut(attempt_id=attempt.id, **_summary_body(attempt))


def _summary_body(attempt: AssessmentAttempt) -> Dict[str, Any]:
    summary = dict(attempt.summary or {})
    summary.pop("attempt_id", None)
    summary.setdefault("subtopic", "")
    summary.setdefault("status", attempt.status)
    summary.setdefault("kind", attempt.kind)
    summary.setdefault("total_questions", attempt.questions_answered)
    summary.setdefault("correct", 0)
    summary.setdefault("accuracy", 0.0)
    summary.setdefault(
        "highest_difficulty_reached", attempt.highest_difficulty_reached
    )
    summary.setdefault("hints_used", 0)
    summary.setdefault("mastery_score", attempt.final_mastery_score or 0)
    summary.setdefault("classification", "needs_practice")
    return summary


@router.get("/{attempt_id}/summary", response_model=AttemptSummaryOut)
async def get_summary(attempt_id: uuid.UUID, user: CurrentUser, db: DbSession):
    attempt = await _load_attempt(db, attempt_id, user.id, with_responses=True)
    if attempt.status == "in_progress":
        subtopic, _, _ = await _load_scope(db, attempt.subtopic_id, user.id)
        # a live preview of where they stand, without ending the attempt
        preview = assessment.build_summary(
            attempt, list(attempt.responses), subtopic.title, subtopic.mastery_score
        )
        preview.pop("attempt_id", None)
        return AttemptSummaryOut(attempt_id=attempt.id, **preview)
    return AttemptSummaryOut(attempt_id=attempt.id, **_summary_body(attempt))


@router.get("", response_model=List[Dict[str, Any]])
async def list_attempts(
    user: CurrentUser,
    db: DbSession,
    subtopic_id: Optional[uuid.UUID] = None,
    limit: int = 20,
):
    stmt = select(AssessmentAttempt).where(AssessmentAttempt.user_id == user.id)
    if subtopic_id:
        stmt = stmt.where(AssessmentAttempt.subtopic_id == subtopic_id)
    attempts = (
        await db.scalars(
            stmt.order_by(AssessmentAttempt.started_at.desc()).limit(min(limit, 100))
        )
    ).all()
    return [
        {
            "attempt_id": str(a.id),
            "subtopic_id": str(a.subtopic_id),
            "kind": a.kind,
            "status": a.status,
            "questions_answered": a.questions_answered,
            "highest_difficulty_reached": a.highest_difficulty_reached,
            "final_mastery_score": a.final_mastery_score,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "completed_at": a.completed_at.isoformat() if a.completed_at else None,
            "classification": (a.summary or {}).get("classification"),
        }
        for a in attempts
    ]

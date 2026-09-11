"""Adaptive assessment engine (PRD 7.3, 7.4, 7.6).

Implements the finalised rule set:
  * level up   after 2 consecutive correct at the current level
  * level down after 2 consecutive incorrect at the current level
  * rolling mastery_score (0-100) updated after EVERY question
  * attempt ends at max_questions, or early when mastery is confidently
    high or low
  * mastery decays over time (PRD open question 2)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AssessmentAttempt,
    QuestionPool,
    QuestionResponse,
    Subject,
    Subtopic,
    Topic,
)
from app.services import llm, prompts

logger = logging.getLogger(__name__)

LADDER = ["basic", "medium", "hard"]
POOL_SIZE = 6

# mastery points awarded/deducted per question, by difficulty
GAIN = {"basic": 6, "medium": 10, "hard": 15}
LOSS = {"basic": 10, "medium": 6, "hard": 3}


# --------------------------------------------------------------------------
# Mastery
# --------------------------------------------------------------------------


def decayed_mastery(score: int, updated_at: Optional[datetime]) -> int:
    """Apply time decay so stale mastery doesn't read as current knowledge."""
    if not score or not updated_at:
        return score or 0
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - updated_at).total_seconds() / 86400
    if days <= 1:
        return score
    decayed = score - settings.mastery_decay_per_day * (days - 1)
    # never decay below a floor — they did learn it once
    return max(int(round(decayed)), min(score, 20))


def apply_mastery_delta(
    current: int, difficulty: str, is_correct: bool, hints_used: int
) -> int:
    if is_correct:
        delta = GAIN.get(difficulty, 6)
        if hints_used:
            delta = max(1, delta - 3 * hints_used)
    else:
        delta = -LOSS.get(difficulty, 6)
    return max(0, min(100, current + delta))


# --------------------------------------------------------------------------
# Ladder
# --------------------------------------------------------------------------


def step_difficulty(
    current: str, correct_streak: int, incorrect_streak: int
) -> Tuple[str, int, int]:
    """Returns (next_difficulty, correct_streak, incorrect_streak)."""
    idx = LADDER.index(current) if current in LADDER else 0

    if correct_streak >= settings.level_up_streak and idx < len(LADDER) - 1:
        return LADDER[idx + 1], 0, 0
    if incorrect_streak >= settings.level_down_streak and idx > 0:
        return LADDER[idx - 1], 0, 0
    return current, correct_streak, incorrect_streak


def should_stop(attempt: AssessmentAttempt, mastery: int) -> bool:
    if attempt.questions_answered >= attempt.max_questions:
        return True
    # early exit: clearly mastered
    if (
        attempt.current_difficulty == "hard"
        and mastery >= 90
        and attempt.questions_answered >= 5
    ):
        return True
    # early exit: clearly struggling — stop rather than grind them down
    if (
        attempt.current_difficulty == "basic"
        and mastery <= 10
        and attempt.questions_answered >= 5
    ):
        return True
    return False


# --------------------------------------------------------------------------
# Question pools (generated once, reused — PRD 11 cost control)
# --------------------------------------------------------------------------


def _normalise_theory(raw: List[Dict[str, Any]], difficulty: str) -> List[Dict[str, Any]]:
    out = []
    for i, q in enumerate(raw):
        question = str(q.get("question", "")).strip()
        answer = str(q.get("answer", "")).strip()
        if not question or not answer:
            continue
        options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        if options and answer not in options:
            # model paraphrased the answer — match loosely, else drop options
            match = next(
                (o for o in options if answer.lower() in o.lower() or o.lower() in answer.lower()),
                None,
            )
            if match:
                answer = match
            else:
                options = []
        out.append(
            {
                "id": f"{difficulty}-{i}-{uuid.uuid4().hex[:6]}",
                "kind": "theory",
                "difficulty": difficulty,
                "question": question,
                "options": options or None,
                "answer": answer,
                "explanation": str(q.get("explanation", "")).strip(),
                "concept": str(q.get("concept", "")).strip(),
            }
        )
    return out


def _normalise_coding(raw: List[Dict[str, Any]], difficulty: str) -> List[Dict[str, Any]]:
    out = []
    for i, q in enumerate(raw):
        prompt_text = str(q.get("prompt", "")).strip()
        tests = q.get("tests") or []
        if not prompt_text or not tests:
            continue
        clean_tests = []
        for j, t in enumerate(tests[:8]):
            call = str(t.get("call", "")).strip()
            if not call:
                continue
            clean_tests.append(
                {
                    "name": str(t.get("name") or f"case {j + 1}"),
                    "call": call,
                    "expected": str(t.get("expected", "")).strip(),
                }
            )
        if not clean_tests:
            continue
        out.append(
            {
                "id": f"{difficulty}-{i}-{uuid.uuid4().hex[:6]}",
                "kind": "coding",
                "difficulty": difficulty,
                "title": str(q.get("title", "Coding problem")).strip(),
                "question": prompt_text,
                "starter_code": str(q.get("starter_code") or "def solve():\n    pass\n"),
                "tests": clean_tests,
                "solution": str(q.get("solution", "")).strip(),
                "concept": str(q.get("concept", "")).strip(),
            }
        )
    return out


async def ensure_pool(
    db: AsyncSession,
    *,
    subtopic: Subtopic,
    topic: Topic,
    subject: Subject,
    difficulty: str,
    kind: str,
    language: str,
    context: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return a cached pool, generating it once if missing."""
    pool = await db.scalar(
        select(QuestionPool).where(
            QuestionPool.subtopic_id == subtopic.id,
            QuestionPool.difficulty == difficulty,
        )
    )
    if pool and pool.questions:
        return pool.questions

    try:
        if kind == "coding":
            data = await llm.complete_json(
                prompts.build_coding_question_messages(
                    subject=subject.name,
                    topic=topic.title,
                    subtopic=subtopic.title,
                    difficulty=difficulty,
                    count=POOL_SIZE,
                    language=language,
                ),
                lane_name="background",
                max_tokens=6000,
            )
            questions = _normalise_coding(data.get("questions") or [], difficulty)
        else:
            data = await llm.complete_json(
                prompts.build_theory_question_messages(
                    subject=subject.name,
                    topic=topic.title,
                    subtopic=subtopic.title,
                    difficulty=difficulty,
                    count=POOL_SIZE,
                    language=language,
                    context=context,
                ),
                lane_name="background",
            )
            questions = _normalise_theory(data.get("questions") or [], difficulty)
    except llm.LLMUnavailable as exc:
        logger.error("Question generation unavailable: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Question generation failed: %s", exc)
        return []

    if not questions:
        return []

    if pool:
        pool.questions = questions
        pool.kind = kind
    else:
        db.add(
            QuestionPool(
                subtopic_id=subtopic.id,
                difficulty=difficulty,
                kind=kind,
                questions=questions,
            )
        )
    await db.flush()
    return questions


def pick_question(
    pool: List[Dict[str, Any]], served_ids: List[str]
) -> Optional[Dict[str, Any]]:
    for q in pool:
        if q["id"] not in served_ids:
            return q
    return pool[0] if pool else None  # recycle rather than dead-end the attempt


def public_question(q: Dict[str, Any]) -> Dict[str, Any]:
    """Strip answers/solutions before sending to the client."""
    out = {
        "id": q["id"],
        "difficulty": q["difficulty"],
        "kind": q.get("kind", "theory"),
        "question": q["question"],
    }
    if q.get("kind") == "coding":
        out["starter_code"] = q.get("starter_code")
        out["visible_tests"] = [
            {"name": t["name"], "input": t["call"], "expected": t["expected"]}
            for t in (q.get("tests") or [])[:2]
        ]
        if q.get("title"):
            out["question"] = f"### {q['title']}\n\n{q['question']}"
    else:
        out["options"] = q.get("options")
    return out


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------


def _normalise_answer(text: str) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .")


async def grade_theory(
    question: Dict[str, Any], answer: str, language: str
) -> Tuple[bool, str]:
    """MCQ is graded locally; free text goes to the LLM."""
    expected = question.get("answer", "")

    if question.get("options"):
        given = _normalise_answer(answer)
        target = _normalise_answer(expected)
        if given == target:
            return True, ""
        # accept an option letter or index ("B", "2")
        options = question["options"]
        if len(given) == 1 and given.isalpha():
            idx = ord(given) - ord("a")
            if 0 <= idx < len(options):
                return _normalise_answer(options[idx]) == target, ""
        if given.isdigit():
            idx = int(given) - 1
            if 0 <= idx < len(options):
                return _normalise_answer(options[idx]) == target, ""
        return False, ""

    if _normalise_answer(answer) == _normalise_answer(expected):
        return True, ""

    try:
        data = await llm.complete_json(
            prompts.build_grade_messages(
                question=question["question"],
                expected=expected,
                answer=answer,
                language=language,
            ),
            lane_name="interactive",
            max_tokens=512,
        )
        return bool(data.get("is_correct")), str(data.get("feedback", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM grading failed (%s); using literal match", exc)
        return False, ""


async def explain_answer(
    question: Dict[str, Any], answer: str, is_correct: bool, language: str
) -> str:
    try:
        result = await llm.complete(
            prompts.build_feedback_messages(
                question=question["question"],
                options=question.get("options"),
                correct_answer=question.get("answer", ""),
                user_answer=answer,
                is_correct=is_correct,
                explanation=question.get("explanation", ""),
                language=language,
            ),
            lane_name="interactive",
            max_tokens=512,
        )
        if result.provider != "none":
            return result.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Feedback generation failed: %s", exc)

    # deterministic fallback so the student always gets something useful
    base = question.get("explanation") or ""
    if is_correct:
        return f"Correct. {base}".strip()
    return f"Not quite — the answer is: {question.get('answer', '')}. {base}".strip()


# --------------------------------------------------------------------------
# Classification & summary (PRD 7.6)
# --------------------------------------------------------------------------


def classify(
    accuracy: float, highest_difficulty: str, mastery: int
) -> str:
    if mastery >= 70 and highest_difficulty in ("hard", "medium") and accuracy >= 0.7:
        return "strength"
    if mastery <= 40 or accuracy < 0.5:
        return "weakness"
    return "needs_practice"


def build_summary(
    attempt: AssessmentAttempt,
    responses: List[QuestionResponse],
    subtopic_title: str,
    mastery: int,
) -> Dict[str, Any]:
    total = len(responses)
    correct = sum(1 for r in responses if r.is_correct)
    accuracy = (correct / total) if total else 0.0
    hints = sum(r.hints_used for r in responses)

    strengths = sorted(
        {r.question_text[:90] for r in responses if r.is_correct}
    )[:5]
    weaknesses = sorted(
        {r.question_text[:90] for r in responses if not r.is_correct}
    )[:5]

    classification = classify(accuracy, attempt.highest_difficulty_reached, mastery)
    recommendation = {
        "strength": f"You've got {subtopic_title} down. Move on to the next sub-topic.",
        "needs_practice": f"Solid start on {subtopic_title}. Redo the questions you missed, then retest.",
        "weakness": f"Go back and study {subtopic_title} with the tutor before retesting.",
    }[classification]

    return {
        "attempt_id": str(attempt.id),
        "subtopic": subtopic_title,
        "status": attempt.status,
        "kind": attempt.kind,
        "total_questions": total,
        "correct": correct,
        "accuracy": round(accuracy, 3),
        "highest_difficulty_reached": attempt.highest_difficulty_reached,
        "hints_used": hints,
        "mastery_score": mastery,
        "classification": classification,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendation": recommendation,
        "responses": [
            {
                "question": r.question_text,
                "difficulty": r.difficulty,
                "is_correct": r.is_correct,
                "user_answer": r.user_answer,
                "feedback": r.ai_feedback,
                "hints_used": r.hints_used,
                "needed_solution": r.needed_solution,
            }
            for r in responses
        ],
    }

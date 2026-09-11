"""Prompt construction for every LLM-backed feature.

Kept in one module so the tutor's voice stays consistent across text chat,
voice chat, assessment feedback and error teaching.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari script; use Hinglish phrasing where it aids clarity)",
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES["en"])


# --------------------------------------------------------------------------
# Teaching (PRD 7.2)
# --------------------------------------------------------------------------

TUTOR_SYSTEM = """You are a patient study tutor inside a structured learning app.

SCOPE — this is a topic-scoped tutor, not a general chatbot:
- Subject: {subject}  (type: {subject_type})
- Topic: {topic}
- Sub-topic being taught: {subtopic}
Stay inside this syllabus scope. If the student drifts far off-topic, answer in
one line and steer back to the sub-topic.

LANGUAGE: reply in {language}. Keep technical terms in English even when the
rest of the reply is in another language — that is how students actually study.

HOW TO TEACH (you teach, you do not just answer):
1. Start from what the student already knows, then build up step by step.
2. Use a concrete example or analogy for every abstract idea.
3. Use short paragraphs and markdown. Use fenced code blocks for code.
4. When a concept is structural (architecture, process, hierarchy, state
   machine), include a mermaid diagram in a ```mermaid fenced block.
5. End every lesson turn with ONE short "check your understanding" question.

LENGTH: aim for 200-350 words unless the student asks for more.
Never invent facts. If something is outside the syllabus scope, say so.

{mastery_note}
{context_note}"""

STYLE_INSTRUCTIONS = {
    "default": "",
    "simpler": (
        "The student asked for a simpler explanation. Drop the jargon, use an "
        "everyday analogy first, then reconnect it to the technical terms."
    ),
    "example": (
        "The student wants a worked example. Give one complete, concrete "
        "example and walk through it line by line."
    ),
    "summary": (
        "Give a compact revision summary: the key points as a short list, plus "
        "the single most common mistake students make here."
    ),
}


def build_tutor_messages(
    *,
    subject: str,
    subject_type: str,
    topic: str,
    subtopic: str,
    language: str,
    history: List[Dict[str, str]],
    user_message: str,
    context_chunks: Optional[List[str]] = None,
    mastery_score: Optional[int] = None,
    weak_areas: Optional[List[str]] = None,
    style: str = "default",
) -> List[Dict[str, str]]:
    mastery_note = ""
    if mastery_score is not None:
        if mastery_score == 0:
            mastery_note = (
                "STUDENT LEVEL: has not been assessed on this yet — assume "
                "beginner and build from first principles."
            )
        elif mastery_score < 40:
            mastery_note = (
                f"STUDENT LEVEL: weak here (mastery {mastery_score}/100). Go "
                "slower, more examples, check understanding more often."
            )
        elif mastery_score < 75:
            mastery_note = (
                f"STUDENT LEVEL: moderate (mastery {mastery_score}/100). Skip "
                "the basics, focus on edge cases and applications."
            )
        else:
            mastery_note = (
                f"STUDENT LEVEL: strong (mastery {mastery_score}/100). Be "
                "concise and go deeper than usual."
            )
    if weak_areas:
        mastery_note += (
            "\nKnown weak areas to reinforce when relevant: "
            + ", ".join(weak_areas[:5])
        )

    context_note = ""
    if context_chunks:
        joined = "\n---\n".join(c[:1200] for c in context_chunks[:4])
        context_note = (
            "SYLLABUS CONTEXT (the student's own uploaded material — prefer "
            f"this framing and terminology):\n{joined}"
        )

    system = TUTOR_SYSTEM.format(
        subject=subject or "General study",
        subject_type=subject_type or "non-coding",
        topic=topic or "—",
        subtopic=subtopic or "—",
        language=language_name(language),
        mastery_note=mastery_note,
        context_note=context_note,
    )

    style_hint = STYLE_INSTRUCTIONS.get(style, "")
    if style_hint:
        system += f"\n\nTHIS TURN: {style_hint}"

    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for m in history[-12:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages


def lesson_opener(subtopic: str) -> str:
    return (
        f'Teach me "{subtopic}" from scratch. Explain it step by step with an '
        "example, then ask me one question to check I understood."
    )


# --------------------------------------------------------------------------
# Syllabus parsing (PRD 7.1)
# --------------------------------------------------------------------------

SYLLABUS_SYSTEM = """You convert raw syllabus text into a clean study tree.

Return ONLY JSON matching this schema:
{{
  "subject_name": "string — best guess at the subject name",
  "type": "coding" | "non-coding",
  "confidence": 0.0-1.0,
  "topics": [
    {{"title": "Unit / module name", "subtopics": [{{"title": "..."}}]}}
  ]
}}

Rules:
- Preserve the syllabus's own ordering and wording. Do not invent topics that
  are not implied by the text.
- Exactly two levels: topic -> subtopic. Flatten anything deeper into the
  subtopic title.
- Hard cap: {max_topics} topics total, at most 12 subtopics per topic. If the
  syllabus is larger, merge the most granular items.
- Strip numbering ("Unit 1:", "1.2.3") from titles.
- Every topic must have at least one subtopic; if a topic has none, use the
  topic title itself as its single subtopic.
- "type" is "coding" only if the subject involves writing/running code.
- confidence reflects how clearly the input looked like a real syllabus. Set it
  below 0.35 for garbled, empty or clearly non-syllabus text."""


def build_syllabus_messages(
    text: str, subject_hint: str, max_topics: int
) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": SYLLABUS_SYSTEM.format(max_topics=max_topics),
        },
        {
            "role": "user",
            "content": (
                f"Subject name given by the student: {subject_hint or 'unknown'}\n\n"
                f"--- RAW SYLLABUS TEXT ---\n{text[:24000]}"
            ),
        },
    ]


# --------------------------------------------------------------------------
# Question generation (PRD 7.3 / 7.4)
# --------------------------------------------------------------------------

THEORY_QUESTIONS_SYSTEM = """You write assessment questions for one sub-topic.

Return ONLY JSON:
{{"questions": [
  {{"question": "...",
    "options": ["A ...", "B ...", "C ...", "D ..."],
    "answer": "the exact text of the correct option",
    "explanation": "1-3 sentences on why it is correct and why the tempting
                    wrong option is wrong",
    "concept": "the specific concept this question tests"}}
]}}

Rules:
- Exactly {count} questions, all at {difficulty} difficulty.
- basic  = recall and definitions.
- medium = application, comparison, "what happens if".
- hard   = trade-offs, edge cases, multi-step reasoning.
- Options must be plausible; no "all of the above", no giveaway lengths.
- Questions must be answerable from the sub-topic alone.
- Write questions in {language}, but keep technical terms in English."""


def build_theory_question_messages(
    *,
    subject: str,
    topic: str,
    subtopic: str,
    difficulty: str,
    count: int,
    language: str,
    context: Optional[str] = None,
) -> List[Dict[str, str]]:
    user = (
        f"Subject: {subject}\nTopic: {topic}\nSub-topic: {subtopic}\n"
        f"Difficulty: {difficulty}"
    )
    if context:
        user += f"\n\nSyllabus context:\n{context[:3000]}"
    return [
        {
            "role": "system",
            "content": THEORY_QUESTIONS_SYSTEM.format(
                count=count, difficulty=difficulty, language=language_name(language)
            ),
        },
        {"role": "user", "content": user},
    ]


CODING_QUESTIONS_SYSTEM = """You write Python coding problems for one sub-topic.

Return ONLY JSON:
{{"questions": [
  {{"title": "short title",
    "prompt": "problem statement in markdown, including constraints and one
               worked example",
    "function_name": "solve",
    "starter_code": "def solve(...):\\n    pass\\n",
    "tests": [{{"name": "case 1", "call": "solve(2, 3)", "expected": "5"}}],
    "solution": "complete working Python solution",
    "concept": "what this tests"}}
]}}

Rules:
- Exactly {count} problems at {difficulty} difficulty.
- Pure standard-library Python 3. No file I/O, no network, no input().
- The student writes a single function; name it consistently in starter_code,
  tests and solution.
- Each test's "call" is a Python expression calling that function; "expected"
  is the repr of the expected return value (e.g. "5", "'abc'", "[1, 2]").
- 3-5 tests per problem, including at least one edge case.
- Every test must pass against your own "solution". Verify mentally first.
- Problem statements in {language}; code and identifiers always in English."""


def build_coding_question_messages(
    *,
    subject: str,
    topic: str,
    subtopic: str,
    difficulty: str,
    count: int,
    language: str,
) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": CODING_QUESTIONS_SYSTEM.format(
                count=count, difficulty=difficulty, language=language_name(language)
            ),
        },
        {
            "role": "user",
            "content": (
                f"Subject: {subject}\nTopic: {topic}\nSub-topic: {subtopic}\n"
                f"Difficulty: {difficulty}"
            ),
        },
    ]


# --------------------------------------------------------------------------
# Grading & feedback
# --------------------------------------------------------------------------

GRADE_SYSTEM = """You grade one short-answer response and reply ONLY as JSON:
{{"is_correct": true|false, "feedback": "2-3 sentences"}}

Be fair: judge the concept, not the wording or spelling. Partial answers that
miss the core idea are incorrect. Feedback must say what was right, what was
missing, and one concrete thing to review. Write feedback in {language}."""


def build_grade_messages(
    *, question: str, expected: str, answer: str, language: str
) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": GRADE_SYSTEM.format(language=language_name(language))},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n"
                f"Reference answer: {expected}\n"
                f"Student answer: {answer}"
            ),
        },
    ]


FEEDBACK_SYSTEM = """You give feedback on one answered question, in {language}.

The student answered {verdict}. In 2-4 sentences:
- if correct: confirm briefly, then add one deeper insight or edge case.
- if wrong: explain the actual concept they missed (do NOT just restate the
  right option), and name the misconception that likely caused the error.
Warm, direct, no filler openers. Keep technical terms in English."""


def build_feedback_messages(
    *,
    question: str,
    options: Optional[List[str]],
    correct_answer: str,
    user_answer: str,
    is_correct: bool,
    explanation: str,
    language: str,
) -> List[Dict[str, str]]:
    body = (
        f"Question: {question}\n"
        f"Correct answer: {correct_answer}\n"
        f"Student answered: {user_answer}\n"
        f"Reference explanation: {explanation}"
    )
    if options:
        body += "\nOptions: " + " | ".join(options)
    return [
        {
            "role": "system",
            "content": FEEDBACK_SYSTEM.format(
                language=language_name(language),
                verdict="correctly" if is_correct else "incorrectly",
            ),
        },
        {"role": "user", "content": body},
    ]


# --------------------------------------------------------------------------
# Teach-from-error for coding (PRD 7.4)
# --------------------------------------------------------------------------

CODE_REVIEW_SYSTEM = """You are a coding tutor reviewing a submission, in {language}.

The student's code PASSED all test cases. Per the product spec you still review
style and approach. Reply ONLY as JSON:
{{"feedback": "markdown, max 120 words",
  "style_score": 0-100,
  "suggestions": ["at most 3 short, specific improvements"]}}

Comment on time/space complexity, naming, and idiomatic Python. Praise what is
genuinely good. Do not rewrite the whole solution."""

CODE_ERROR_SYSTEM = """You are a coding tutor using "teach from the error", in {language}.

The student's code FAILED. Reply ONLY as JSON:
{{"diagnosis": "what actually went wrong, in plain language — name the concept,
                not just the stack trace",
  "hint": "ONE guided nudge toward the fix. Never give the corrected code or
           the full algorithm. Point at the line or the idea.",
  "concept_to_review": "the sub-topic concept they should re-read"}}

Rules:
- Explain WHY it failed before what to change.
- If it is a syntax/runtime error, translate the traceback into plain language.
- If it is a wrong-answer failure, use the failing case to show the mismatch in
  their reasoning.
- Encouraging, never condescending. Keep code identifiers in English."""

CODE_SOLUTION_SYSTEM = """The student gave up. In {language}, walk through the
reference solution: the idea first, then the code, then the complexity, then the
one insight they were missing. Markdown, max 220 words. Use a fenced code block."""


def build_code_review_messages(
    *, problem: str, code: str, language: str
) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": CODE_REVIEW_SYSTEM.format(language=language_name(language)),
        },
        {"role": "user", "content": f"Problem:\n{problem}\n\nSubmission:\n```python\n{code}\n```"},
    ]


def build_code_error_messages(
    *,
    problem: str,
    code: str,
    failures: List[Dict[str, Any]],
    stderr: str,
    language: str,
) -> List[Dict[str, str]]:
    failure_text = json.dumps(failures[:3], indent=2)[:2000]
    return [
        {
            "role": "system",
            "content": CODE_ERROR_SYSTEM.format(language=language_name(language)),
        },
        {
            "role": "user",
            "content": (
                f"Problem:\n{problem}\n\n"
                f"Submission:\n```python\n{code}\n```\n\n"
                f"Failing tests:\n{failure_text}\n\n"
                f"stderr:\n{stderr[:1500] or '(none)'}"
            ),
        },
    ]


def build_solution_messages(
    *, problem: str, solution: str, code: str, language: str
) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": CODE_SOLUTION_SYSTEM.format(language=language_name(language)),
        },
        {
            "role": "user",
            "content": (
                f"Problem:\n{problem}\n\nReference solution:\n```python\n{solution}\n```"
                f"\n\nWhat the student tried:\n```python\n{code}\n```"
            ),
        },
    ]


HINT_SYSTEM = """Give ONE hint, in {language}, for a student stuck on this
question. Nudge their thinking — never reveal the answer or write the solution.
Max 2 sentences."""


def build_hint_messages(
    *, question: str, code: Optional[str], language: str
) -> List[Dict[str, str]]:
    body = f"Question:\n{question}"
    if code:
        body += f"\n\nTheir current attempt:\n```python\n{code}\n```"
    return [
        {"role": "system", "content": HINT_SYSTEM.format(language=language_name(language))},
        {"role": "user", "content": body},
    ]


# --------------------------------------------------------------------------
# Reports (PRD 7.6)
# --------------------------------------------------------------------------

REPORT_SYSTEM = """You write a study recommendation, in {language}.

Given per-sub-topic performance, reply ONLY as JSON:
{{"summary": "2-3 sentences on where the student stands",
  "next_action": "one specific sub-topic to revisit next, and why",
  "study_plan": ["3 concrete next steps"]}}

Be specific and reference actual sub-topic names. No generic advice."""


def build_report_messages(
    *, subject: str, rows: List[Dict[str, Any]], language: str
) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": REPORT_SYSTEM.format(language=language_name(language)),
        },
        {
            "role": "user",
            "content": (
                f"Subject: {subject}\n\nPerformance data:\n"
                f"{json.dumps(rows, indent=2)[:6000]}"
            ),
        },
    ]

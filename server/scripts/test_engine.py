"""Unit checks for the offline logic: adaptive ladder, mastery decay,
grading and the syllabus fallback parser. No database or API keys needed.

    python scripts/test_engine.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import assessment, syllabus  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    checks.append((name, condition, detail))
    print(f"{'[ok]' if condition else '[XX]'} {name}" + (f" — {detail}" if detail else ""))


def test_ladder() -> None:
    # 2 consecutive correct promotes (PRD 7.3)
    nxt, c, i = assessment.step_difficulty("basic", 2, 0)
    check("2 correct promotes basic -> medium", (nxt, c, i) == ("medium", 0, 0), nxt)

    nxt, _, _ = assessment.step_difficulty("medium", 2, 0)
    check("2 correct promotes medium -> hard", nxt == "hard", nxt)

    # 1 correct does not
    nxt, c, _ = assessment.step_difficulty("basic", 1, 0)
    check("1 correct holds level", (nxt, c) == ("basic", 1), nxt)

    # 2 consecutive incorrect demotes
    nxt, _, i = assessment.step_difficulty("hard", 0, 2)
    check("2 wrong demotes hard -> medium", (nxt, i) == ("medium", 0), nxt)

    # cannot go below basic or above hard
    nxt, _, _ = assessment.step_difficulty("basic", 0, 2)
    check("basic is the floor", nxt == "basic", nxt)
    nxt, _, _ = assessment.step_difficulty("hard", 5, 0)
    check("hard is the ceiling", nxt == "hard", nxt)


def test_mastery() -> None:
    # correct answers gain more at higher difficulty
    basic = assessment.apply_mastery_delta(50, "basic", True, 0)
    hard = assessment.apply_mastery_delta(50, "hard", True, 0)
    check("hard correct gains more than basic", hard > basic, f"{basic} vs {hard}")

    # wrong at basic costs more than wrong at hard
    wrong_basic = assessment.apply_mastery_delta(50, "basic", False, 0)
    wrong_hard = assessment.apply_mastery_delta(50, "hard", False, 0)
    check(
        "wrong at basic costs more than at hard",
        wrong_basic < wrong_hard,
        f"{wrong_basic} vs {wrong_hard}",
    )

    # hints reduce the gain
    with_hint = assessment.apply_mastery_delta(50, "medium", True, 2)
    without = assessment.apply_mastery_delta(50, "medium", True, 0)
    check("hints reduce mastery gained", with_hint < without, f"{with_hint} vs {without}")

    # clamped to 0..100
    check("clamps at 100", assessment.apply_mastery_delta(98, "hard", True, 0) == 100)
    check("clamps at 0", assessment.apply_mastery_delta(2, "basic", False, 0) == 0)


def test_decay() -> None:
    now = datetime.now(timezone.utc)
    check("fresh score does not decay", assessment.decayed_mastery(80, now) == 80)

    week_old = assessment.decayed_mastery(80, now - timedelta(days=7))
    check("week-old score decays", week_old < 80, f"80 -> {week_old}")

    year_old = assessment.decayed_mastery(80, now - timedelta(days=365))
    check("decay has a floor", year_old > 0, f"floor={year_old}")

    check("zero stays zero", assessment.decayed_mastery(0, now - timedelta(days=30)) == 0)


def test_classification() -> None:
    check(
        "high accuracy at hard = strength",
        assessment.classify(0.9, "hard", 85) == "strength",
    )
    check(
        "low accuracy stuck at basic = weakness",
        assessment.classify(0.3, "basic", 20) == "weakness",
    )
    check(
        "mixed = needs practice",
        assessment.classify(0.6, "medium", 55) == "needs_practice",
    )


def test_stop_conditions() -> None:
    class FakeAttempt:
        def __init__(self, answered, max_q, difficulty):
            self.questions_answered = answered
            self.max_questions = max_q
            self.current_difficulty = difficulty

    check("stops at max questions", assessment.should_stop(FakeAttempt(10, 10, "medium"), 50))
    check("continues mid-test", not assessment.should_stop(FakeAttempt(4, 10, "medium"), 50))
    check(
        "early exit when mastered",
        assessment.should_stop(FakeAttempt(6, 10, "hard"), 95),
    )
    check(
        "early exit when struggling",
        assessment.should_stop(FakeAttempt(6, 10, "basic"), 5),
    )


def test_grading() -> None:
    mcq = {
        "question": "Which normal form removes partial dependency?",
        "options": ["1NF", "2NF", "3NF", "BCNF"],
        "answer": "2NF",
    }
    for label, answer, expected in [
        ("exact option text", "2NF", True),
        ("case insensitive", "2nf", True),
        ("option letter", "B", True),
        ("option number", "2", True),
        ("wrong option", "3NF", False),
    ]:
        correct, _ = asyncio.run(assessment.grade_theory(mcq, answer, "en"))
        check(f"MCQ graded by {label}", correct == expected, f"{answer!r} -> {correct}")


def test_public_question_hides_answers() -> None:
    q = {
        "id": "x",
        "difficulty": "basic",
        "kind": "theory",
        "question": "Q?",
        "options": ["a", "b"],
        "answer": "b",
        "explanation": "because",
    }
    public = assessment.public_question(q)
    check(
        "theory answer is never sent to the client",
        "answer" not in public and "explanation" not in public,
        str(sorted(public)),
    )

    coding = {
        "id": "y",
        "difficulty": "hard",
        "kind": "coding",
        "question": "Write it",
        "starter_code": "def solve(): pass",
        "tests": [
            {"name": "t1", "call": "solve()", "expected": "1"},
            {"name": "t2", "call": "solve()", "expected": "2"},
            {"name": "t3", "call": "solve()", "expected": "3"},
        ],
        "solution": "def solve(): return 1",
    }
    public = assessment.public_question(coding)
    check(
        "coding solution is never sent to the client",
        "solution" not in public and "tests" not in public,
        str(sorted(public)),
    )
    check(
        "only sample tests are exposed",
        len(public["visible_tests"]) == 2,
        f"{len(public['visible_tests'])} of 3",
    )


def test_syllabus_fallback() -> None:
    raw = """
    Unit 1: Introduction to Databases
    Data models, Schema and instances, Three-schema architecture
    DBMS vs File system

    Unit 2: Relational Model
    Relational algebra, Tuple calculus, Integrity constraints

    Unit 3: Normalization
    Functional dependencies, 1NF, 2NF, 3NF, BCNF
    """
    tree = syllabus.heuristic_tree(raw)
    check("heuristic parser finds units", len(tree) == 3, f"{len(tree)} topics")
    check(
        "numbering is stripped from titles",
        tree and tree[0]["title"] == "Introduction to Databases",
        tree[0]["title"] if tree else "",
    )
    check(
        "comma lists become sub-topics",
        tree and len(tree[0]["subtopics"]) >= 3,
        f"{len(tree[0]['subtopics'])} sub-topics" if tree else "",
    )

    chunks = syllabus.chunk_text("word " * 2000)
    check("chunker splits long text", len(chunks) > 1, f"{len(chunks)} chunks")
    check("chunker handles empty input", syllabus.chunk_text("") == [])


def main() -> int:
    for section, fn in [
        ("Adaptive ladder (PRD 7.3)", test_ladder),
        ("Mastery scoring", test_mastery),
        ("Mastery decay (open question 2)", test_decay),
        ("Classification (PRD 7.6)", test_classification),
        ("Stop conditions", test_stop_conditions),
        ("Theory grading", test_grading),
        ("Answer leakage", test_public_question_hides_answers),
        ("Syllabus fallback (PRD 7.1)", test_syllabus_fallback),
    ]:
        print(f"\n--- {section} ---")
        fn()

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Deep verification of the differentiating features (needs a running server
and API keys): syllabus upload -> tree -> pgvector indexing, streaming lessons,
the coding assessment loop with teach-from-error, and text-to-speech.

    python scripts/test_features.py
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8000"
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"{'[ok]' if ok else '[XX]'} {name}" + (f" — {detail}" if detail else ""))


SYLLABUS = """
DATABASE MANAGEMENT SYSTEMS - COURSE SYLLABUS

Unit 1: Introduction to Database Systems
Purpose of database systems, View of data, Data abstraction, Instances and schemas,
Data models, Database languages, Database architecture, Database users and administrators

Unit 2: Relational Model
Structure of relational databases, Database schema, Keys, Relational algebra,
Tuple relational calculus, Domain relational calculus

Unit 3: SQL
Basic SQL query structure, Set operations, Aggregate functions, Nested subqueries,
Modification of the database, Join expressions, Views, Integrity constraints

Unit 4: Normalization
Features of good relational design, Functional dependencies, Decomposition,
First normal form, Second normal form, Third normal form, BCNF, Multivalued dependencies

Unit 5: Transaction Management
Transaction concept, ACID properties, Transaction states, Concurrent executions,
Serializability, Recoverability, Lock based protocols, Deadlock handling
"""


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=180.0)

    health = c.get("/health/full").json()
    if health["llm"]["degraded"]:
        print("LLM providers are degraded — configure keys first.")
        return 2
    check("providers ready", True, f"gemini={health['llm']['gemini']['ok']} groq={health['llm']['groq']['ok']}")

    email = f"feat-{uuid.uuid4().hex[:8]}@example.com"
    token = c.post(
        "/auth/signup",
        json={"email": email, "name": "Feature Test", "password": "test-password-123"},
    ).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"

    # ---------------------------------------------------------------
    # 1. Syllabus upload -> AI-parsed draft tree (PRD 7.1)
    # ---------------------------------------------------------------
    print("\n--- Syllabus parsing (PRD 7.1) ---")
    resp = c.post(
        "/subjects/upload",
        files={"file": ("dbms_syllabus.txt", SYLLABUS.encode(), "text/plain")},
        data={"name": "Database Management Systems", "type": "non-coding"},
    )
    if resp.status_code != 201:
        check("syllabus upload", False, resp.text[:300])
        return 1
    parsed = resp.json()
    subject_id = parsed["subject_id"]
    topics = parsed["topics"]
    check(
        "syllabus parsed into a tree",
        len(topics) >= 4,
        f"{len(topics)} topics, confidence={parsed['confidence']}",
    )
    check("subject starts as draft (open q4)", parsed["status"] == "draft", parsed["status"])
    check(
        "numbering stripped from titles",
        topics and not topics[0]["title"].lower().startswith("unit"),
        topics[0]["title"] if topics else "",
    )
    check(
        "sub-topics extracted",
        topics and len(topics[0]["subtopics"]) >= 3,
        f"{sum(len(t['subtopics']) for t in topics)} sub-topics total",
    )

    # tree is not live until confirmed
    tree = c.get(f"/subjects/{subject_id}/tree").json()
    check("nothing committed before confirm", len(tree["topics"]) == 0, f"{len(tree['topics'])} topics")

    confirmed = c.post(f"/subjects/{subject_id}/confirm", json={"topics": topics})
    if confirmed.status_code != 200:
        check("confirm tree", False, confirmed.text[:300])
        return 1
    tree = confirmed.json()
    check(
        "tree committed on confirm",
        tree["status"] == "active" and len(tree["topics"]) >= 4,
        f"{tree['progress']['total_subtopics']} sub-topics",
    )

    # ---------------------------------------------------------------
    # 2. pgvector indexing (PRD 7.2)
    # ---------------------------------------------------------------
    print("\n--- Vector retrieval (PRD 7.2) ---")
    import asyncio

    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import ContentChunk

    async def count_chunks():
        async with SessionLocal() as db:
            total = await db.scalar(
                select(func.count(ContentChunk.id)).where(
                    ContentChunk.subject_id == uuid.UUID(subject_id)
                )
            )
            embedded = await db.scalar(
                select(func.count(ContentChunk.id)).where(
                    ContentChunk.subject_id == uuid.UUID(subject_id),
                    ContentChunk.embedding.is_not(None),
                )
            )
            return total, embedded

    total, embedded = asyncio.run(count_chunks())
    check("syllabus indexed into pgvector", total > 0 and embedded == total, f"{embedded}/{total} chunks embedded")

    # ---------------------------------------------------------------
    # 3. Streaming lesson (PRD 11 latency)
    # ---------------------------------------------------------------
    print("\n--- Streaming tutor (PRD 11) ---")
    norm = next(
        (t for t in tree["topics"] if "normal" in t["title"].lower()), tree["topics"][0]
    )
    subtopic = norm["subtopics"][0]
    subtopic_id = subtopic["id"]

    events, tokens, provider = [], [], None
    with c.stream(
        "POST",
        "/teach/stream",
        json={"subtopic_id": subtopic_id, "message": "Teach me this in 3 sentences."},
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            events.append(ev["type"])
            if ev["type"] == "token":
                tokens.append(ev["value"])
            if ev["type"] == "provider":
                provider = ev["value"]

    check("stream emits session id", "session" in events)
    check("stream emits tokens", len(tokens) > 0, f"{len(tokens)} chunks from {provider}")
    check("stream signals done", events[-1] == "done", events[-1])

    lesson = "".join(tokens)
    check("lesson has real content", len(lesson) > 100, f"{len(lesson)} chars")

    sessions = c.get("/teach/sessions", params={"subtopic_id": subtopic_id}).json()
    persisted = sessions and len(sessions[0]["messages"]) >= 2
    check("transcript persisted after stream", bool(persisted),
          f"{len(sessions[0]['messages']) if sessions else 0} messages")

    # topic-scoping: the tutor should know the subject context
    reply = c.post(
        "/teach",
        json={"subtopic_id": subtopic_id, "message": "What subject am I studying?"},
    ).json()
    check("tutor stays in syllabus scope", "database" in reply["reply"].lower(),
          reply["reply"][:70].replace("\n", " "))

    # ---------------------------------------------------------------
    # 4. Coding assessment + teach-from-error (PRD 7.4)
    # ---------------------------------------------------------------
    print("\n--- Coding assessment + sandbox (PRD 7.4) ---")
    coding = c.post(
        "/subjects",
        json={
            "name": "Python Programming",
            "type": "coding",
            "topics": [{"title": "Basics", "subtopics": [{"title": "Loops and lists"}]}],
        },
    ).json()
    code_subtopic = coding["topics"][0]["subtopics"][0]["id"]
    c.patch(f"/subtopics/{code_subtopic}", json={"is_completed": True})

    started = c.post("/assessments/start", json={"subtopic_id": code_subtopic})
    if started.status_code != 201:
        check("coding assessment start", False, started.text[:300])
        return 1
    state = started.json()
    attempt_id = state["attempt_id"]
    q = state["question"]
    check("coding question generated", q["kind"] == "coding", q["question"][:60].replace("\n", " "))
    check("starter code provided", bool(q.get("starter_code")), (q.get("starter_code") or "")[:40])
    check("sample tests visible", bool(q.get("visible_tests")), f"{len(q.get('visible_tests') or [])} shown")
    check("reference solution hidden", "solution" not in q and "tests" not in q, str(sorted(q)))

    # submit deliberately broken code -> expect teach-from-error
    broken = c.post(
        f"/assessments/{attempt_id}/submit-code",
        json={"code": "def solve(x):\n    return None\n"},
    ).json()
    check("failing submission reported", broken["passed"] is False)
    check("error diagnosis returned", len(broken["feedback"]) > 40, broken["feedback"][:70].replace("\n", " "))
    check("guided hint returned (not the answer)", bool(broken.get("hint")), (broken.get("hint") or "")[:70])
    check(
        "failing submission does NOT consume the question",
        broken["state"]["questions_answered"] == 0,
        f"answered={broken['state']['questions_answered']}",
    )

    # a hint should be available on demand
    hint = c.post(f"/assessments/{attempt_id}/hint", json={"code": "def solve(x): pass"}).json()
    check("on-demand hint", len(hint["hint"]) > 10, hint["hint"][:70].replace("\n", " "))

    # give up -> solution walkthrough, question consumed, mastery penalised
    gave_up = c.post(
        f"/assessments/{attempt_id}/submit-code",
        json={"code": "def solve(x):\n    return None\n", "give_up": True},
    ).json()
    check("give-up reveals solution", bool(gave_up.get("solution")), (gave_up.get("solution") or "")[:50].replace("\n", " "))
    check("give-up gives a walkthrough", len(gave_up["feedback"]) > 40, gave_up["feedback"][:70].replace("\n", " "))
    check(
        "give-up consumes the question",
        gave_up["state"]["questions_answered"] == 1,
        f"answered={gave_up['state']['questions_answered']}",
    )

    summary = c.get(f"/assessments/{attempt_id}/summary").json()
    check("needed-help recorded in summary", summary["total_questions"] >= 1,
          f"{summary['correct']}/{summary['total_questions']} -> {summary['classification']}")

    # ---------------------------------------------------------------
    # 5. Voice (PRD 7.5)
    # ---------------------------------------------------------------
    print("\n--- Voice (PRD 7.5) ---")
    for lang, label in [("en", "English"), ("hi", "Hindi")]:
        text = "Normalization removes redundancy." if lang == "en" else "सामान्यीकरण डेटा दोहराव को कम करता है।"
        resp = c.post("/voice/speak", json={"text": text, "language": lang}).json()
        ok = resp.get("voice_enabled") and resp.get("audio_url")
        detail = resp.get("audio_url") or resp.get("message", "")
        if ok:
            audio = httpx.get(BASE + resp["audio_url"], timeout=60)
            ok = audio.status_code == 200 and len(audio.content) > 1000
            detail = f"{len(audio.content)} bytes mp3"
        check(f"TTS {label}", bool(ok), str(detail)[:70])

    langs = c.get("/voice/languages").json()
    check("STT configured", langs["stt"]["configured"], langs["stt"]["model"])

    # ---------------------------------------------------------------
    # 6. Report
    # ---------------------------------------------------------------
    print("\n--- Report (PRD 7.6) ---")
    report = c.get(f"/reports/{coding['id']}").json()
    check(
        "report classifies and recommends",
        bool(report["next_recommendation"]),
        report["next_recommendation"][:80].replace("\n", " "),
    )

    # cleanup
    c.delete(f"/subjects/{subject_id}")
    c.delete(f"/subjects/{coding['id']}")

    failed = [x for x in checks if not x[1]]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.ConnectError:
        print(f"Could not reach {BASE} — is the server running?")
        sys.exit(2)

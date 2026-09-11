"""End-to-end smoke test against a running server.

Exercises the full PRD flow: signup -> subject -> tree -> complete a sub-topic
-> teach -> assessment -> report -> pomodoro. AI-backed steps are reported as
SKIP (not FAIL) when no API key is configured, so this is also useful as a
pre-demo check.

    python scripts/smoke_test.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    symbol = {PASS: "[ok]", FAIL: "[XX]", SKIP: "[--]"}[status]
    print(f"{symbol} {name}" + (f" — {detail}" if detail else ""))


def main(base_url: str) -> int:
    client = httpx.Client(base_url=base_url, timeout=120.0)

    # --- health ---
    health = client.get("/health/full").json()
    record("health", PASS, f"db={health['database']['ok']} llm_degraded={health['llm']['degraded']}")
    ai_ready = not health["llm"]["degraded"]
    if not ai_ready:
        print("    (no working LLM key — AI steps will be skipped)\n")

    # --- auth ---
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={"email": email, "name": "Smoke Test", "password": "test-password-123"},
    )
    if resp.status_code != 201:
        record("auth/signup", FAIL, resp.text[:200])
        return 1
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    record("auth/signup", PASS, email)

    if client.get("/auth/me").status_code == 200:
        record("auth/me", PASS)
    else:
        record("auth/me", FAIL)

    if client.post("/auth/login", json={"email": email, "password": "wrong"}).status_code == 401:
        record("auth rejects bad password", PASS)
    else:
        record("auth rejects bad password", FAIL)

    unauth = httpx.Client(base_url=base_url, timeout=30.0)
    if unauth.get("/subjects").status_code == 401:
        record("routes require auth", PASS)
    else:
        record("routes require auth", FAIL)

    # --- subject + tree ---
    resp = client.post(
        "/subjects",
        json={
            "name": "Database Management Systems",
            "type": "non-coding",
            "topics": [
                {
                    "title": "Normalization",
                    "subtopics": [{"title": "First Normal Form"}, {"title": "BCNF"}],
                },
                {"title": "Transactions", "subtopics": [{"title": "ACID properties"}]},
            ],
        },
    )
    if resp.status_code != 201:
        record("subjects create", FAIL, resp.text[:200])
        return 1
    subject = resp.json()
    subject_id = subject["id"]
    subtopic_id = subject["topics"][0]["subtopics"][0]["id"]
    record("subjects create", PASS, f"{len(subject['topics'])} topics")

    tree = client.get(f"/subjects/{subject_id}/tree").json()
    record("subjects tree", PASS, f"{tree['progress']['total_subtopics']} sub-topics")

    # --- checkbox tree ---
    resp = client.patch(f"/subtopics/{subtopic_id}", json={"is_completed": True})
    if resp.status_code == 200 and resp.json()["is_completed"]:
        record("subtopic mark complete", PASS)
    else:
        record("subtopic mark complete", FAIL, resp.text[:200])

    # --- 50-topic cap (PRD open question 5) ---
    resp = client.post(
        "/subjects",
        json={
            "name": "Too Big",
            "topics": [{"title": f"T{i}", "subtopics": []} for i in range(60)],
        },
    )
    if resp.status_code == 400:
        record("topic cap enforced", PASS, "60 topics rejected")
    else:
        record("topic cap enforced", FAIL, f"got {resp.status_code}")

    # --- pomodoro ---
    resp = client.post(
        "/pomodoro/start", json={"subject_id": subject_id, "planned_minutes": 25}
    )
    if resp.status_code == 201:
        session_id = resp.json()["id"]
        client.post(f"/pomodoro/{session_id}/stop", params={"duration_minutes": 25})
        stats = client.get("/pomodoro/stats").json()
        record("pomodoro cycle", PASS, f"{stats['total_minutes']} min logged")
    else:
        record("pomodoro cycle", FAIL, resp.text[:200])

    # --- teaching (AI) ---
    if ai_ready:
        resp = client.post(
            "/teach",
            json={"subtopic_id": subtopic_id, "message": "Teach me 1NF in two sentences."},
        )
        if resp.status_code == 200 and resp.json()["provider"] != "none":
            data = resp.json()
            record("teach", PASS, f"{data['provider']}, {len(data['reply'])} chars")
        else:
            record("teach", FAIL, resp.text[:200])
    else:
        record("teach", SKIP, "no LLM key")

    # --- assessment (AI) ---
    if ai_ready:
        resp = client.post("/assessments/start", json={"subtopic_id": subtopic_id})
        if resp.status_code == 201:
            state = resp.json()
            attempt_id = state["attempt_id"]
            record("assessment start", PASS, f"Q: {state['question']['question'][:60]}...")

            answered = 0
            while state.get("question") and answered < 3:
                question = state["question"]
                answer = (question.get("options") or ["I don't know"])[0]
                resp = client.post(
                    f"/assessments/{attempt_id}/answer", json={"answer": answer}
                )
                if resp.status_code != 200:
                    record("assessment answer", FAIL, resp.text[:200])
                    break
                body = resp.json()
                state = body["state"]
                answered += 1
            else:
                record(
                    "assessment answer loop",
                    PASS,
                    f"{answered} answered, difficulty={state['current_difficulty']}",
                )

            summary = client.get(f"/assessments/{attempt_id}/summary").json()
            record(
                "assessment summary",
                PASS,
                f"{summary['correct']}/{summary['total_questions']} -> {summary['classification']}",
            )
        else:
            record("assessment start", FAIL, resp.text[:300])
    else:
        record("assessment", SKIP, "no LLM key")

    # --- report ---
    resp = client.get(f"/reports/{subject_id}", params={"ai_summary": ai_ready})
    if resp.status_code == 200:
        r = resp.json()
        record(
            "report",
            PASS,
            f"mastery={r['overall_mastery']} strengths={len(r['strengths'])} "
            f"weaknesses={len(r['weaknesses'])} untested={len(r['untested'])}",
        )
    else:
        record("report", FAIL, resp.text[:200])

    # --- cascade delete (PRD section 11 data privacy) ---
    if client.delete(f"/subjects/{subject_id}").status_code == 204:
        gone = client.get(f"/subjects/{subject_id}/tree").status_code == 404
        record("subject delete cascades", PASS if gone else FAIL)
    else:
        record("subject delete cascades", FAIL)

    # --- summary ---
    failed = [r for r in results if r[1] == FAIL]
    skipped = [r for r in results if r[1] == SKIP]
    print(
        f"\n{len(results) - len(failed) - len(skipped)} passed, "
        f"{len(failed)} failed, {len(skipped)} skipped"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        sys.exit(main(args.base_url))
    except httpx.ConnectError:
        print(f"Could not reach {args.base_url} — is the server running?")
        sys.exit(2)

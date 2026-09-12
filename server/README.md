# AI Smart Study Companion — Backend

FastAPI + PostgreSQL (pgvector) backend implementing the Phase 1 MVP in
[AI-Smart-Study-Companion-PRD.md](AI-Smart-Study-Companion-PRD.md).

---

## Quick start

From the repo root, `npm run setup` then `npm run dev` starts this backend
along with the database and frontend. To run only the backend:

```bash
npm run dev:api          # from the repo root
```

<details>
<summary>Manual steps, if you prefer</summary>

```bash
cd server

docker compose up -d                 # Postgres 16 + pgvector on host port 5433
python -m venv .venv
.venv\Scripts\activate               # Windows
# source .venv/bin/activate          # macOS / Linux
pip install -r requirements.txt
cp .env.example .env                 # then add your API keys
alembic upgrade head
docker pull python:3.12-slim         # sandbox runner for coding assessments

# Use the venv's python; a bare `uvicorn` may resolve to a global install
# that does not have this project's dependencies.
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

</details>

Interactive API docs: <http://127.0.0.1:8000/docs>
Pre-demo health check: <http://127.0.0.1:8000/health/full>

### API keys (both free, no credit card)

| Key | Where | Format |
|---|---|---|
| `GEMINI_API_KEY` | <https://aistudio.google.com/app/apikey> | starts with `AIza` |
| `GROQ_API_KEY` | <https://console.groq.com/keys> | starts with `gsk_` |

The Groq key also powers Whisper speech-to-text. Without keys the server still
runs — AI endpoints return a graceful degraded message rather than erroring.

---

## Verifying it works

```bash
python scripts/test_engine.py     # adaptive ladder, mastery, decay, parsing (no keys needed)
python scripts/test_sandbox.py    # code execution + security constraints (needs Docker)
python scripts/smoke_test.py      # full API flow against a running server
python scripts/test_features.py   # syllabus parsing, streaming, coding loop, voice (needs keys)
python scripts/test_verification.py  # accuracy guardrails (buffering offline, auditors need keys)
```

`smoke_test.py` reports AI-backed steps as **SKIP** rather than fail when no key
is configured, so it doubles as the pre-demo check from PRD §10.1.

---

## Architecture

```
app/
  main.py           FastAPI app, CORS, static file mounts
  config.py         settings (.env)
  database.py       async engine + session
  models.py         ORM — PRD §8 data model
  schemas.py        request/response models
  security.py       bcrypt + JWT
  deps.py           auth dependency

  routers/
    auth.py         signup / login / Google OAuth / profile
    subjects.py     subject containers, syllabus upload, tree confirm
    topics.py       topic + sub-topic checkbox tree
    teach.py        teaching chat (streaming + non-streaming)
    assessments.py  adaptive theory ladder + coding sandbox loop
    reports.py      strength / weakness analysis
    voice.py        STT, TTS, full voice round trip
    pomodoro.py     focus sessions + stats
    health.py       readiness incl. both LLM providers

  services/
    llm.py          Gemini -> Groq routing, streaming, JSON mode, embeddings
    prompts.py      every prompt in the product, in one place
    throttle.py     two-lane rate limiting for free-tier quotas
    syllabus.py     PDF extraction -> topic tree (+ offline fallback)
    retrieval.py    pgvector search (+ keyword fallback)
    teaching.py     shared chat-session logic
    assessment.py   adaptive ladder, mastery scoring, decay, classification
    verifier.py     accuracy guardrails: sentence audits + the critique loop
    sandbox.py      Docker-isolated Python execution
    voice.py        Groq Whisper STT + edge-tts TTS
    storage.py      file storage behind a swappable interface
```

### Decisions taken from the PRD's open questions

| PRD question | Decision | Where |
|---|---|---|
| 1. Voice languages | English + Hindi | `config.supported_languages` |
| 2. Mastery over time | Decays ~1.5 pts/day after a 1-day grace, with a floor | `assessment.decayed_mastery` |
| 3. Coding grading | Test cases decide pass/fail; the LLM also reviews style on passing code | `routers/assessments.submit_code` |
| 4. AI tree confirmation | Explicit — upload creates `status='draft'`, nothing enters the tree until `/confirm` | `routers/subjects` |
| 5. Sub-topic granularity | 50 topics/subject, 12 sub-topics/topic, exactly 2 levels | `_write_tree`, `syllabus._normalise` |

### LLM routing (PRD §10.1)

> **Model IDs differ from the PRD.** Every model the PRD named has since been
> retired — `gemini-2.5-flash`/`-lite` return *"no longer available to new
> users"*, `llama-3.3-70b-versatile` is gone from Groq, and
> `text-embedding-004` is withdrawn. The table below is what is actually live,
> verified against both APIs. Change these in `.env` if the providers move again.

| Use case | Model | PRD had |
|---|---|---|
| Tutor chat turns | `gemini-3.5-flash-lite` | `gemini-2.5-flash-lite` |
| Question generation, syllabus parsing (JSON) | `gemini-3.5-flash` | `gemini-2.5-flash` |
| Fallback for both | `openai/gpt-oss-120b` (Groq) | `llama-3.3-70b-versatile` |
| Embeddings (768-dim) | `gemini-embedding-001` | `text-embedding-004` |
| Speech to text | `whisper-large-v3-turbo` (Groq) | same |
| Text to speech | `edge-tts`, falling back to `gemini-2.5-flash-preview-tts` | "TBD" |

Every model call goes through `services/llm.py`:

- **Gemini first**, **Groq fallback** on any Gemini error, not just 429.
- **Graceful degradation** — if both fail, users get a clear message and
  `voice_enabled: false` instead of a 500.

Groq's `gpt-oss` is a reasoning model that spends completion tokens before
emitting content, so calls set `reasoning_effort: "low"` (roughly halves the
overhead) and never use a tiny `max_tokens`.

Streaming falls back to Groq only if Gemini fails *before* the first token —
switching providers mid-sentence would produce incoherent output.

**Three rate-limit lanes** (PRD §11) keep background work from starving live
tutoring: `interactive` (tutor turns, grading, hints), `background` (question
pools, embeddings, report summaries) and `verify` (accuracy audits).

---

## Accuracy guardrails

LLM output can contain a wrong formula, an invented definition, or a claim that
contradicts the uploaded syllabus. Speaking that aloud to a student is worse
than saying nothing, so two tiers of verification sit in front of it. Both use
the fast model tier and their own rate-limit lane.

### Track 1 — live chat, before text-to-speech

| Step | Behaviour |
|---|---|
| Streaming | Tokens reach the UI immediately. Audits run as background tasks and never block a token. |
| Buffering | Tokens are buffered server-side to sentence boundaries. Fenced code and mermaid blocks are excluded — they are not spoken. |
| Pre-filter | Sentences under 25 characters or fewer than 3 words carry no checkable claim and are skipped, saving quota. |
| Audit | Remaining sentences are scored 0-100 against the question and the retrieved syllabus context, at temperature 0. |
| ≥ 80 | Approved. The sentence is spoken exactly as written. |
| < 80 | Intercepted. A corrected rewrite is what reaches TTS — the false claim is never vocalised — and a correction note is appended to the transcript. |

Audits are **batched four sentences per request**. Sentence-level verdicts are
preserved (each gets its own score, rewrite and note), but a 14-sentence answer
costs 4 requests rather than 14. That took end-to-end audit latency from 38s to
about 4s after the last token, and keeps the guardrail inside a free tier.

The stream emits one extra SSE event per sentence:

```json
{"type":"verified","index":3,"approved":false,"score":20,
 "speak":"A primary key cannot contain NULL values.",
 "note":"Correction: primary keys cannot contain NULL values.","checked":true}
```

The client speaks only the assembled `speak` text. If the auditor is
unreachable the sentence passes through with `checked:false` — an unavailable
auditor degrades to "spoken as written" rather than silencing the tutor.

### Track 2 — critical tasks, before the UI or the database

Question pools, official solutions and grading are gated: nothing unverified is
rendered or stored.

1. Generate, then audit the complete content for factual accuracy,
   solvability, fairness and scope.
2. **≥ 80** → approved.
3. **< 80** → discard and regenerate **once**, armed with the auditor's
   specific critique. Total attempts are hard-capped at 2 — there is no path
   that loops.
4. Still failing → return the canonical disclaimer pointing at the syllabus
   section. A wrong answer key would corrupt a student's mastery score, so
   storing nothing is the correct outcome.

### Settings

All in `.env` (see `.env.example`): `VERIFICATION_ENABLED`,
`VERIFICATION_THRESHOLD` (80), `VERIFICATION_MAX_ATTEMPTS` (2),
`VERIFY_LIVE_CHAT`, `VERIFICATION_MIN_CHARS` (25), `VERIFIER_MODEL`,
`LLM_VERIFY_RPM`.

Set `VERIFY_LIVE_CHAT=false` to keep the Track 2 gate but skip live-chat
audits if quota is tight.

### Cost

Roughly one extra request per four tutor sentences, and one extra request per
question pool (two if the first attempt is rejected). Pools are cached, so a
retake costs nothing.

### Cost control

Question pools are generated **once per sub-topic per difficulty** and cached in
`question_pools`, so retaking an assessment costs no LLM quota. Syllabus
extraction is cached on the subject row.

---

## Code execution sandbox

Each submission runs in a throwaway container:

```
--network none          no network access
--memory 256m           memory cap
--cpus 0.5              CPU cap
--pids-limit 64         no fork bombs
--read-only + tmpfs     no writable filesystem outside /tmp
--user 65534            non-root
```

The student's code gets a hard 8s limit enforced *inside* the sandbox, so
container startup never eats their budget. Submitted code is never `eval`'d in
the API process.

If Docker isn't running, the server falls back to a restricted local subprocess
so a demo doesn't die on a stopped daemon. Set
`SANDBOX_ALLOW_LOCAL_FALLBACK=false` for any shared deployment.

---

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/signup`, `/auth/login`, `/auth/google` | Authentication |
| GET/PATCH | `/auth/me` | Profile + language preference |
| GET/POST | `/subjects` | List / create subject |
| POST | `/subjects/upload` | Upload syllabus PDF → draft tree |
| POST | `/subjects/{id}/confirm` | Commit the reviewed tree |
| GET | `/subjects/{id}/tree` | Tree + progress |
| PUT | `/subjects/{id}/tree` | Bulk tree edit |
| PATCH/DELETE | `/subjects/{id}` | Update / delete (cascades) |
| POST | `/subjects/{id}/topics` | Add a topic |
| PATCH/DELETE | `/topics/{id}` | Rename, tick, reorder, delete |
| POST | `/topics/{id}/subtopics` | Add a sub-topic |
| PATCH/DELETE | `/subtopics/{id}` | Tick a sub-topic (feeds assessments) |
| POST | `/teach` | Teaching turn (JSON response) |
| POST | `/teach/stream` | Teaching turn (SSE, token by token) |
| GET/DELETE | `/teach/sessions[/{id}]` | Chat history |
| POST | `/assessments/start` | Begin an adaptive assessment |
| GET | `/assessments/{id}` | Current question + state |
| POST | `/assessments/{id}/answer` | Submit a theory answer |
| POST | `/assessments/{id}/submit-code` | Submit code (or give up) |
| POST | `/assessments/{id}/hint` | Guided hint |
| POST | `/assessments/{id}/finish` | End early |
| GET | `/assessments/{id}/summary` | Results + mastery |
| GET | `/reports/{subject_id}` | Strength / weakness report |
| POST | `/voice/transcribe` | Speech to text |
| POST | `/voice/speak` | Text to speech |
| POST | `/voice/chat` | Full voice round trip |
| GET | `/voice/languages` | Supported languages + voices |
| POST | `/pomodoro/start`, `/{id}/pause`, `/{id}/resume`, `/{id}/stop` | Focus sessions |
| GET | `/pomodoro/active`, `/sessions`, `/stats` | Session tracking |
| GET | `/health`, `/health/full` | Readiness |

### Streaming a lesson from the frontend

`POST /teach/stream` returns `text/event-stream`. Each event is JSON:

```js
const resp = await fetch("http://127.0.0.1:8000/teach/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  body: JSON.stringify({ subtopic_id, message: "Teach me this" }),
});

const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  for (const line of value.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    const ev = JSON.parse(line.slice(6));
    if (ev.type === "token") appendToUI(ev.value);
    if (ev.type === "done") finish();
  }
}
```

Event types: `session` (carries `session_id`), `provider`, `token`, `done`, `error`.

The transcript is persisted server-side after the stream closes, so a dropped
connection never leaves a half-written lesson.

---

## Notes for the frontend

- All endpoints except `/health*` and `/auth/*` need `Authorization: Bearer <jwt>`.
- Lessons come back as **markdown**; ` ```mermaid ` blocks are diagrams and
  should be rendered as such.
- Assessment responses never include answers or reference solutions — the
  server holds them (`scripts/test_engine.py` asserts this).
- `/voice/speak` returns `voice_enabled: false` instead of erroring when TTS
  fails for a language; fall back to showing text.
- A failing code submission does **not** consume the question — the student
  keeps iterating with hints until they pass or explicitly `give_up: true`.

---

## Phase 2 hooks already in place

`pomodoro_sessions` and `chat_sessions` carry timestamps from day one, and
`GET /pomodoro/stats` already returns per-day aggregates — the activity
heatmap only needs a frontend.

## for front end
The command
It has to run from client/ — there's no package.json at the repo root:
cd client
npm run dev

## for backend 
 cd server
 docker compose up -d
  uvicorn app.main:app --reload --port 8000

  Currently running
Frontend	http://localhost:5173
Backend	http://127.0.0.1:8000 (docs)
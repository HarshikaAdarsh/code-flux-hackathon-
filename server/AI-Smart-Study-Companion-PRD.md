# AI-Based Smart Study Companion — Product Requirements Document (PRD)

**Version:** 0.1 (Draft)
**Status:** Phase 1 (MVP) scoping
**Owner:** [Your Name]
**Last updated:** 2026-09-11

---

## 1. Problem Statement

Existing AI chatbots used for studying fail learners in four consistent ways:

| Gap in existing chatbots | Consequence |
|---|---|
| No structured content | Student doesn't know what to study next, or how much is left |
| No real "teach me this" interaction | Chatbot answers questions but doesn't *teach* a topic step by step |
| Few/no visualizations | Concepts that need diagrams are explained only in text |
| No voice-based teaching in natural / native language | Slower retention — people learn faster hearing explanations in a language and format they're comfortable with |

**Product thesis:** A study companion that containerizes every subject into a syllabus tree, teaches interactively (text + voice, multilingual), tests adaptively, and shows the student exactly where they're weak — closing the loop between *learning* and *evaluation*.

---

## 2. Goals (Phase 1 / MVP)

1. Let a user create subject containers from an uploaded syllabus (auto-parsed) or manually.
2. Let a user mark topics/sub-topics complete via a checkbox tree.
3. Provide a chatbot, on the same screen as the tree, that teaches a specific topic on request.
4. Provide adaptive assessments (theory ladder for non-coding, code+sandbox+"teach from error" for coding).
5. Show strength/weakness breakdown per subject based on test results.
6. Provide authentication.
7. Provide a multilingual voice assistant (mic in → voice out).
8. Provide a Pomodoro-style focus timer tied to study sessions.

**Non-goals for Phase 1:** activity/streak visualizations (Phase 2), social/multiplayer features, offline mode, native mobile apps.

---

## 3. Primary User Persona

**"Rahul", 20, engineering student**
- Studies 3–4 subjects per semester, some coding (Python, DSA), some theory (DBMS, OS).
- Has PDF syllabus from college but no structured way to track progress.
- Prefers explanations in Hinglish/native language when concepts get hard.
- Currently pastes doubts into a generic chatbot and gets unstructured, one-shot answers with no memory of what he already knows.

---

## 4. Feature List — Phase 1 vs Phase 2

| # | Feature | Phase |
|---|---|---|
| 1 | Subject containerization + syllabus upload + topic tree w/ checkboxes | 1 |
| 2 | Contextual teaching chatbot (text) | 1 |
| 3 | Adaptive subject assessment (theory ladder + coding sandbox + error-teaching) | 1 |
| 4 | Strength/weakness report | 1 |
| 5 | Authentication | 1 |
| 6 | Multilingual voice assistant (STT in, TTS out) | 1 |
| 7 | Pomodoro focus session | 1 |
| 8 | Activity/study-time visualizations & heatmaps | 2 |

---

## 5. System Architecture (High Level)

```mermaid
flowchart TB
    subgraph Client["Client (Web App)"]
        UI[React/Next.js UI]
        Mic[Mic Input Module]
        Editor[Code Editor - Monaco]
        Timer[Pomodoro Timer]
    end

    subgraph Gateway["API Gateway / Backend"]
        Auth[Auth Service]
        SubjectSvc[Subject & Syllabus Service]
        TeachSvc[Teaching / Chat Service]
        AssessSvc[Assessment Engine]
        VoiceSvc[Voice Service]
        AnalyticsSvc[Analytics Service]
    end

    subgraph AI["AI Layer"]
        LLM[LLM Router - Gemini primary / Groq fallback]
        STT[Speech-to-Text]
        TTS[Text-to-Speech]
        Extractor[Syllabus Parser]
    end

    subgraph Infra["Execution & Storage"]
        Sandbox[Code Execution Sandbox]
        DB[(Primary DB - Postgres)]
        VectorDB[(Vector DB - topic/content embeddings)]
        FileStore[(File Storage - S3/Blob - PDFs)]
    end

    UI --> Auth
    UI --> SubjectSvc
    UI --> TeachSvc
    UI --> AssessSvc
    Mic --> VoiceSvc
    Editor --> AssessSvc
    Timer --> AnalyticsSvc

    SubjectSvc --> Extractor
    Extractor --> LLM
    SubjectSvc --> FileStore
    SubjectSvc --> DB

    TeachSvc --> LLM
    TeachSvc --> VectorDB
    TeachSvc --> DB

    AssessSvc --> LLM
    AssessSvc --> Sandbox
    AssessSvc --> DB

    VoiceSvc --> STT
    VoiceSvc --> LLM
    VoiceSvc --> TTS

    AnalyticsSvc --> DB

    Auth --> DB
```

---

## 6. End-to-End Data Flow (Overall)

```mermaid
flowchart LR
    A[User signs up / logs in] --> B[User creates Subject]
    B --> C{Upload syllabus?}
    C -->|Yes| D[PDF sent to backend]
    D --> E[Text extraction + LLM parses topics/sub-topics]
    E --> F[Hierarchical tree generated]
    C -->|No| G[User manually adds topics/sub-topics]
    F --> H[Tree shown with checkboxes]
    G --> H
    H --> I[User studies a topic]
    I --> J[Chatbot teaches - text/voice]
    J --> K[User marks topic complete]
    K --> L[Completed topics feed Assessment pool]
    L --> M[User starts Assessment on a topic]
    M --> N[Adaptive question engine]
    N --> O[User answers]
    O --> P{Correct?}
    P -->|Yes| Q[Difficulty increases]
    P -->|No| R[Difficulty decreases / explain error]
    Q --> S[Results stored]
    R --> S
    S --> T[Strength/Weakness report generated]
    T --> H
```

---

## 7. Feature-Level Flows

### 7.1 Subject Creation & Syllabus Parsing

```mermaid
sequenceDiagram
    actor U as User
    participant UI as Frontend
    participant SS as Subject Service
    participant FS as File Storage
    participant EX as Syllabus Extractor (LLM)
    participant DB as Database

    U->>UI: Click "Add Subject"
    UI->>U: Ask name, type (coding/non-coding), syllabus upload (optional)
    alt Syllabus uploaded
        U->>UI: Upload PDF
        UI->>SS: POST /subjects {file, type, name}
        SS->>FS: Store PDF
        SS->>EX: Send extracted PDF text
        EX->>EX: Identify topics/sub-topics, build JSON tree
        EX-->>SS: Hierarchical JSON {topic, subtopics[]}
        SS->>DB: Save subject + tree (status: draft)
        SS-->>UI: Return generated tree for review
        UI->>U: Show editable tree (confirm/edit before saving)
        U->>UI: Confirm tree
        UI->>SS: POST /subjects/{id}/confirm
        SS->>DB: Save tree (status: active)
    else No syllabus
        U->>UI: Manually add topic/sub-topic nodes
        UI->>SS: POST /subjects {name, type, tree: manual}
        SS->>DB: Save subject + tree
    end
    SS-->>UI: Redirect to Subject page (tree view)
```

**Notes / edge cases**
- Extraction must degrade gracefully: scanned/image PDFs → OCR fallback → if still low confidence, fall back to "manual entry" with a message.
- Tree is always user-editable post-generation (add/rename/delete nodes) — auto-extraction is a starting point, not final.

---

### 7.2 Topic Tree + Teaching Chatbot

```mermaid
sequenceDiagram
    actor U as User
    participant UI as Subject Page (Tree + Chat)
    participant TS as Teaching Service
    participant VDB as Vector DB
    participant LLM as LLM

    U->>UI: Click sub-topic node OR type "teach me X"
    UI->>TS: POST /teach {subject_id, topic_id, mode: text/voice, language}
    TS->>VDB: Fetch relevant context (syllabus scope, prior chat history, user's known weak areas)
    VDB-->>TS: Context chunks
    TS->>LLM: Prompt: teach {topic} within {subject scope}, style=step-by-step, language={x}
    LLM-->>TS: Structured lesson (explanation + example + check-understanding question)
    TS-->>UI: Render lesson (text, code blocks, diagrams if applicable)
    U->>UI: Ask follow-up / "explain again simpler"
    UI->>TS: POST /teach/followup
    TS->>LLM: Continue conversation with topic context retained
    LLM-->>UI: Response
    U->>UI: Mark sub-topic as Completed (checkbox)
    UI->>TS: PATCH /topics/{id} {status: completed}
```

**Key design decision:** the chat is topic-scoped, not a generic open chat — every message carries `subject_id` + `topic_id` context so the LLM stays within syllabus boundaries and prior lesson history.

---

### 7.3 Adaptive Assessment — Non-Coding Subject

```mermaid
flowchart TD
    Start[User selects completed topic for assessment] --> Gen[AI generates question pool: Basic/Medium/Hard]
    Gen --> ShowB[Show Basic question]
    ShowB --> AnsB{Answered correctly?}
    AnsB -->|Yes, 2 in a row| ShowM[Show Medium question]
    AnsB -->|No| ShowB2[Show another Basic question]
    ShowM --> AnsM{Answered correctly?}
    AnsM -->|Yes, 2 in a row| ShowH[Show Hard question]
    AnsM -->|No| DropB[Drop back to Basic]
    ShowH --> AnsH{Answered correctly?}
    AnsH -->|Yes| RecordMastery[Mark topic mastery: High]
    AnsH -->|No| DropM[Drop back to Medium]
    DropB --> ShowB
    DropM --> ShowM
    RecordMastery --> End[Show test summary + strengths/weaknesses]
```

**Adaptive rule set (to finalize):**
- Level-up threshold: 2 consecutive correct at current level.
- Level-down threshold: 2 consecutive incorrect at current level.
- Each topic gets a rolling `mastery_score` (0–100) updated after every question, not just at test end.
- Test ends after N questions (configurable, default 10) or when mastery confidence is high/low enough to stop early.

---

### 7.4 Adaptive Assessment — Coding Subject (with "teach from error")

```mermaid
flowchart TD
    Start[User selects completed coding topic] --> GenQ[AI generates coding problem at current difficulty]
    GenQ --> ShowEditor[Show problem + code editor]
    ShowEditor --> Submit[User submits code]
    Submit --> Sandbox[Send code to execution sandbox]
    Sandbox --> RunTests[Run against test cases]
    RunTests --> Result{All tests pass?}
    Result -->|Yes| ShowSuccess[Show pass + output, increase difficulty]
    Result -->|No| Analyze[Send code + failing test + error trace to LLM]
    Analyze --> Explain[LLM explains WHY it failed, in natural language, in user's preferred language]
    Explain --> Guide[LLM gives guided hint - not full solution - toward the fix]
    Guide --> Retry{User retries?}
    Retry -->|Yes| Submit
    Retry -->|No, gives up| ShowSolution[Reveal solution + walkthrough]
    ShowSuccess --> Next[Next problem, higher difficulty]
    ShowSolution --> Record[Record as 'needed help' - lowers mastery score]
    Next --> End[Session summary]
    Record --> End
```

**Sandbox constraints:** containerized execution (e.g., Docker per submission), CPU/memory/time limits, no network access, language-specific runners (Python first for MVP).

---

### 7.5 Multilingual Voice Assistant

```mermaid
sequenceDiagram
    actor U as User
    participant UI as Frontend (Mic button)
    participant VS as Voice Service
    participant STT as Speech-to-Text
    participant TS as Teaching Service (LLM)
    participant TTS as Text-to-Speech

    U->>UI: Press mic, speak in native language
    UI->>VS: Stream audio
    VS->>STT: Transcribe (auto-detect or user-set language)
    STT-->>VS: Text + detected language
    VS->>TS: Forward as normal teach/chat request (+ language tag)
    TS-->>VS: Text response (LLM answer)
    VS->>TTS: Synthesize speech in same language
    TTS-->>VS: Audio stream
    VS-->>UI: Play audio response
    UI->>U: Hears answer in voice mode
```

**Phase 1 scope decision needed:** which languages are actually supported (e.g., English + Hindi first; expand regional languages later) — STT/TTS quality varies a lot by language and this affects timeline.

---

### 7.6 Strength / Weakness Reporting

```mermaid
flowchart LR
    A[Assessment attempts stored per question] --> B[Aggregate by sub-topic]
    B --> C[Compute accuracy %, avg difficulty reached, hints used]
    C --> D{Classify}
    D -->|High accuracy, reached Hard| E[Strength]
    D -->|Low accuracy, stuck at Basic/Medium| F[Weakness]
    D -->|Mixed| G[Needs Practice]
    E --> H[Report page: Strengths / Weaknesses / Needs Practice]
    F --> H
    G --> H
    H --> I[Suggest next topic to revisit or study]
```

---

### 7.7 Authentication

```mermaid
sequenceDiagram
    actor U as User
    participant UI as Frontend
    participant AS as Auth Service
    participant DB as Database

    U->>UI: Sign up / Log in (email+password or OAuth)
    UI->>AS: POST /auth/signup or /auth/login
    AS->>DB: Verify/create user record
    AS-->>UI: JWT / session token
    UI->>UI: Store token, attach to all subsequent API calls
```

---

### 7.8 Pomodoro Focus Session

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Focusing: User clicks Start
    Focusing --> Paused: User clicks Pause/Break
    Paused --> Focusing: User clicks Resume
    Focusing --> SessionComplete: Timer hits configured duration
    SessionComplete --> Idle: Log session to Analytics Service
    Paused --> Idle: User ends session early
```

Each completed/paused session is logged with `subject_id`, `topic_id` (optional), duration, and timestamps — this data feeds Phase 2 activity visualizations.

---

## 8. Data Model (Entity Relationship Overview)

```mermaid
erDiagram
    USER ||--o{ SUBJECT : owns
    SUBJECT ||--o{ TOPIC : contains
    TOPIC ||--o{ SUBTOPIC : contains
    SUBTOPIC ||--o{ CHAT_SESSION : "taught via"
    SUBTOPIC ||--o{ ASSESSMENT_ATTEMPT : "tested via"
    USER ||--o{ ASSESSMENT_ATTEMPT : takes
    ASSESSMENT_ATTEMPT ||--o{ QUESTION_RESPONSE : has
    SUBJECT ||--o{ POMODORO_SESSION : "tracked for"
    USER ||--o{ POMODORO_SESSION : logs

    USER {
        uuid id PK
        string email
        string name
        string password_hash
        string preferred_language
    }
    SUBJECT {
        uuid id PK
        uuid user_id FK
        string name
        string type "coding|non-coding"
        string syllabus_file_url
        timestamp created_at
    }
    TOPIC {
        uuid id PK
        uuid subject_id FK
        string title
        int order_index
        bool is_completed
    }
    SUBTOPIC {
        uuid id PK
        uuid topic_id FK
        string title
        bool is_completed
        int mastery_score
    }
    CHAT_SESSION {
        uuid id PK
        uuid subtopic_id FK
        uuid user_id FK
        string mode "text|voice"
        string language
        jsonb messages
        timestamp created_at
    }
    ASSESSMENT_ATTEMPT {
        uuid id PK
        uuid subtopic_id FK
        uuid user_id FK
        string status
        int final_mastery_score
        timestamp started_at
        timestamp completed_at
    }
    QUESTION_RESPONSE {
        uuid id PK
        uuid attempt_id FK
        string question_text
        string difficulty "basic|medium|hard"
        bool is_correct
        string user_answer
        string ai_feedback
        int hints_used
    }
    POMODORO_SESSION {
        uuid id PK
        uuid user_id FK
        uuid subject_id FK
        int duration_minutes
        timestamp started_at
        timestamp ended_at
    }
```

---

## 9. API Surface (Indicative)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/signup` / `/auth/login` | Authentication |
| POST | `/subjects` | Create subject (with/without syllabus) |
| POST | `/subjects/{id}/confirm` | Confirm AI-generated tree |
| GET | `/subjects/{id}/tree` | Get topic/sub-topic tree |
| PATCH | `/topics/{id}` | Mark complete/incomplete, edit |
| POST | `/teach` | Start/continue a teaching chat session |
| POST | `/voice/transcribe` | STT for mic input |
| POST | `/voice/speak` | TTS for response |
| POST | `/assessments/start` | Begin adaptive assessment on a sub-topic |
| POST | `/assessments/{id}/answer` | Submit answer (theory) |
| POST | `/assessments/{id}/submit-code` | Submit code (coding) |
| GET | `/assessments/{id}/summary` | Get results + mastery updates |
| GET | `/reports/{subject_id}` | Strength/weakness report |
| POST | `/pomodoro/start` / `/pomodoro/stop` | Focus session tracking |

---

## 10. Suggested Tech Stack (Phase 1)

| Layer | Suggestion | Why |
|---|---|---|
| Frontend | React | Fast iteration, good ecosystem for editors (Monaco) and audio |
| Backend | Node.js (expressJS) or python (fastAPI)  | FastAPI pairs naturally with AI/ML tooling if extraction/sandbox logic lives in Python |
| Database | PostgreSQL | Relational structure fits subject→topic→subtopic tree + assessment history well |
| Vector store | pgvector (inside Postgres) or a managed vector DB | Keep infra simple for MVP — pgvector avoids a second database |
| File storage | S3-compatible blob storage | Syllabus PDFs |
| LLM | Gemini 2.5 Flash-Lite (primary) + Groq Llama 3.3 70B (fallback) | Teaching, syllabus parsing, question generation, error explanation — see §10.1 for routing details |
| Code execution | Docker-based sandbox (e.g., Judge0 self-hosted or similar) | Isolation + language runners out of the box |
| STT/TTS | Groq Whisper (STT, free tier) + evaluate TTS provider for regional language coverage | Whisper included free on Groq (2,000 audio requests/day); TTS provider TBD — evaluate before committing |
| Auth | JWT + OAuth (Google) | Standard, low friction for students |

---

### 10.1 LLM Provider Details — Gemini (Primary) + Groq (Fallback)

**Why this pair:** both have generous no-credit-card free tiers, both are fast enough for a live tutoring chat, and the fallback swap is nearly free (same request shape, different URL/key) since Groq exposes an OpenAI-compatible chat completions endpoint.

**Model routing**

| Use case | Model | Why |
|---|---|---|
| Tutor chat turns (teaching, follow-ups) | `gemini-2.5-flash-lite` | Highest free-tier limits — this is the highest-volume call in the product |
| Quiz/question generation, syllabus parsing | `gemini-2.5-flash` (JSON mode) | Needs structured, reliable JSON output more than raw speed |
| Fallback for any of the above | `llama-3.3-70b-versatile` via Groq | Used only when Gemini is rate-limited or erroring |

**Endpoints**

| Provider | Endpoint | Auth |
|---|---|---|
| Gemini | `POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent` | API key in `x-goog-api-key` header |
| Groq | `POST https://api.groq.com/openai/v1/chat/completions` | API key in `Authorization: Bearer {key}` header (OpenAI-style) |

**Getting API keys (no secret key / OAuth needed for either)**

- **Gemini:** go to `aistudio.google.com/app/apikey` → sign in with a Google account → "Create API key" → pick/create a project → copy the key. Key format: starts with `AIza`, ~39 characters.
- **Groq:** go to `console.groq.com` → sign up → `console.groq.com/keys` → "Create API Key" → copy immediately (shown only once). Key format: starts with `gsk_`.

**Free-tier rate limits (know these before demo day — build the fallback around them)**

| Provider / Model | RPM | TPM | RPD | Notes |
|---|---|---|---|---|
| Gemini `flash` | 10 | 250,000 | 250 | Daily quota resets at midnight Pacific (12:30 PM IST) |
| Gemini `flash-lite` | Higher than Flash | — | — | Preferred for high-volume tutor turns |
| Groq (Llama 3.3 70B) | 30 | 6,000–30,000 | 1,000–14,400 | No credit card required |
| Groq Whisper (STT) | — | — | 2,000 audio requests/day | Included free on same account |

**Fallback chain**

```mermaid
flowchart LR
    A[Request needs LLM response] --> B[Call Gemini]
    B --> C{Success?}
    C -->|Yes| D[Return response]
    C -->|429 / error| E[Call Groq - same prompt]
    E --> F{Success?}
    F -->|Yes| D
    F -->|No| G[Return text-only fallback message, skip voice synthesis]
```

**Reference implementation (Python, try/except fallback)**

```python
import requests

GEMINI_KEY = "..."   # starts with AIza
GROQ_KEY = "..."     # starts with gsk_

def call_gemini(prompt: str, model: str = "gemini-2.5-flash-lite") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

def call_groq(prompt: str, model: str = "llama-3.3-70b-versatile") -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def get_llm_response(prompt: str) -> dict:
    """Returns {'text': str, 'voice_enabled': bool, 'provider': str}."""
    try:
        return {"text": call_gemini(prompt), "voice_enabled": True, "provider": "gemini"}
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            pass  # fall through to Groq
        else:
            pass  # any Gemini error also falls through — keep the tutor responsive
    except requests.exceptions.RequestException:
        pass

    try:
        return {"text": call_groq(prompt), "voice_enabled": True, "provider": "groq"}
    except requests.exceptions.RequestException:
        return {
            "text": "I'm having trouble reaching the AI service right now — here's what I can tell you from what we've covered so far.",
            "voice_enabled": False,
            "provider": "none",
        }
```

**Pre-demo health check (run ~60 seconds before demoing)**

```bash
# Gemini
curl -s -o /dev/null -w "Gemini: %{http_code}\n" \
  -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent" \
  -H "x-goog-api-key: $GEMINI_KEY" -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"ping"}]}]}'

# Groq
curl -s -o /dev/null -w "Groq: %{http_code}\n" \
  -X POST "https://api.groq.com/openai/v1/chat/completions" \
  -H "Authorization: Bearer $GROQ_KEY" -H "Content-Type: application/json" \
  -d '{"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":"ping"}]}'
```

**Implication for §5 architecture diagram and §7 flows:** every `LLM` node/participant in the diagrams above (Section 5 system architecture, and the sequence/flow diagrams in Sections 7.1–7.6) now resolves to this Gemini→Groq routing layer rather than a single provider — no diagram structure changes, only the box behind the `LLM` label.

---

## 11. Non-Functional Requirements

- **Latency:** teaching chat responses should stream (token-by-token) to feel responsive, not block on full generation.
- **Cost control:** cache syllabus extraction results; don't regenerate question pools per attempt — generate once, reuse/adapt.
- **Rate-limit resilience:** since both LLM providers are on free tiers (see §10.1), the backend must queue/throttle non-urgent calls (e.g., background question-pool pre-generation) separately from user-facing tutor turns, so a burst of usage doesn't exhaust the daily quota mid-session.
- **Sandbox security:** no network access from user-submitted code; strict timeouts (e.g., 5–10s) and memory caps.
- **Data privacy:** syllabus PDFs and chat transcripts are user-owned; deletion of a subject cascades to its chats/assessments.
- **Language fallback:** if STT/TTS fails for a requested language, fall back to text mode with a clear message rather than failing silently.

---

## 12. Open Questions (need decisions before/while building)

1. Which languages are in scope for voice in Phase 1 — English + Hindi only- yes 
2. Does mastery score persist and decay over time (spaced repetition style), or reset per assessment? -> decay
3. ~~For coding assessment grading — pure test-case based, or does the LLM also review code style/approach?~~ **Decided: both** — test cases determine pass/fail (feeds difficulty ladder), LLM additionally reviews style/approach for the "teach from error" feedback even on passing submissions.
4. Should the AI-generated syllabus tree require explicit user confirmation before becoming "active," or auto-activate with an edit option? (This PRD currently assumes explicit confirmation.) -> yes
5. Max granularity of sub-topics — is there a cap to avoid infinite nesting from a messy syllabus?-> cap of 50 topics 

---

## 13. Phase 2 Preview

- Activity chart / heatmap of study sessions (from `POMODORO_SESSION` + `CHAT_SESSION` timestamps already being logged in Phase 1 — this is why they're in the data model now).
- Spaced-repetition style revision reminders based on mastery decay.
- Peer comparison / leaderboards (optional, needs privacy review).

---


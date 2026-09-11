# Padhlo — Frontend

React + Vite client for the AI Smart Study Companion. Every screen maps to a
Phase 1 feature in [the PRD](../server/AI-Smart-Study-Companion-PRD.md) and talks
to the FastAPI backend in [`../server`](../server).

---

## Running it

The backend must be up first:

```bash
cd ../server
docker compose up -d
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Then:

```bash
npm install
npm run dev          # http://localhost:5173
```

`VITE_API_URL` in `.env` points at the backend (default `http://127.0.0.1:8000`).
The backend's `CORS_ORIGINS` already allows ports 5173 and 3000 on both
`localhost` and `127.0.0.1`.

### Verifying

```bash
node scripts/contract-test.mjs
```

Drives the backend exactly as the app does and asserts that every field the
components read actually exists — the check a type-less fetch layer otherwise
misses. AI-backed steps are skipped when no API key is configured.

---

## Structure

```
src/
  lib/api.js            every backend endpoint, incl. the SSE lesson stream
  lib/icons.jsx         inline icon set
  lib/format.js         mastery colours, clock, tree stats
  lib/useChrome.js      lets a page publish its breadcrumb to the top bar

  context/AuthContext   JWT session, restored from localStorage
  context/ToastContext  transient messages

  components/
    Layout.jsx          top bar, account menu, focus timer, footer
    Markdown.jsx        lesson renderer + lazy-loaded mermaid diagrams
    TreeEditor.jsx      two-level tree editing (review + manual entry)
    Modal.jsx

  features/
    tree/TopicTree      checkbox tree, mastery meters, inline rename
    tutor/TutorPanel    streaming topic-scoped chat
    tutor/useVoice      mic capture + spoken playback
    assessment/TheoryRunner   adaptive question ladder
    assessment/CodingRunner   Monaco editor + sandbox results
    assessment/AttemptSummary results and mastery
    pomodoro/PomodoroWidget   focus sessions

  pages/
    AuthPage        login / signup
    DashboardPage   subject cards, progress, draft prompts
    NewSubjectPage  syllabus upload -> review -> confirm, or manual entry
    SubjectPage     syllabus tree + tutor side by side
    AssessmentPage  theory or coding runner, then the summary
    ReportPage      strengths / weaknesses / needs practice
```

---

## Feature → PRD mapping

| Screen | PRD |
|---|---|
| Login / signup, language preference | §7.7 |
| Syllabus upload → editable draft → confirm | §7.1 (+ open question 4) |
| Topic tree with checkboxes and mastery | §7.2 |
| Streaming tutor chat, scoped to a sub-topic | §7.2, §11 |
| Mic in → voice out | §7.5 |
| Theory ladder with hints | §7.3 |
| Coding problems, sandbox results, teach-from-error | §7.4 |
| Strength / weakness report | §7.6 |
| Focus timer | §7.8 |

Deliberately **not** built: streaks, daily-plan cards, activity heatmaps and
session feeds. Those are Phase 2 in the PRD (§4, §13), so there is no backend
for them and no placeholder UI pretending otherwise.

---

## Notes for whoever picks this up

- **Lessons are markdown.** ` ```mermaid ` blocks render as diagrams;
  `mermaid` is dynamically imported so it only loads when a diagram appears.
- **The tutor streams.** `teach.stream()` parses the SSE frames and returns an
  abort function; the transcript is persisted server-side after the stream
  closes, so a dropped connection never loses a lesson.
- **The server owns assessment logic.** Each answer comes back with the next
  question already chosen — the client never decides difficulty.
- **A failing code submission is not an answer.** The student keeps iterating
  with hints until the tests pass or they explicitly give up; only then does
  the question count.
- **Answers never reach the browser.** The API strips `answer`, `explanation`,
  `solution` and hidden tests from questions; `contract-test.mjs` asserts this.
- **Voice degrades to text.** If TTS fails for a language the backend returns
  `voice_enabled: false` and the UI shows a note instead of failing silently.
- **A retake needs `subtopic_id`**, which the summary payload doesn't carry, so
  it is passed through router state. Deep-linking to a finished attempt hides
  the retake button rather than showing a broken one.

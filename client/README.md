# Padhlo — Frontend

React + Vite client for the AI Smart Study Companion. Every screen maps to a
Phase 1 feature in [the PRD](../server/AI-Smart-Study-Companion-PRD.md) and talks
to the FastAPI backend in [`../server`](../server).

---

## Running it

From the repo root, `npm run dev` starts this frontend along with the backend
and database. To run only the frontend (expects a backend already on port 8000):

```bash
npm run dev:web          # from the repo root
npm run dev              # or from this directory
```

`VITE_API_URL` in `.env` points at the backend (default `http://127.0.0.1:8000`).
The dev server is pinned to port 5173 with `strictPort`, because the backend's
CORS allowlist names that exact port — a silent fallback to 5174 would make
every API call fail.

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
    tutor/useVoice      mic capture, /voice/transcribe, /voice/speak
    assessment/TheoryRunner   adaptive question ladder
    assessment/CodingRunner   Monaco editor + sandbox results
    assessment/AttemptSummary results and mastery
    pomodoro/PomodoroWidget   focus sessions

  pages/
    AuthPage        login / signup / Google
    DashboardPage   subject cards, progress, draft prompts
    NewSubjectPage  syllabus upload -> review -> confirm, or manual entry
    SubjectPage     syllabus tree + tutor side by side, subject settings
    AssessmentPage  theory or coding runner, then the summary
    ReportPage      strengths / weaknesses / needs practice
    HistoryPage     past lessons, past tests, focus sessions
    NotFoundPage    404
```

---

## Feature → PRD mapping

| Screen | PRD |
|---|---|
| Login / signup, Google OAuth, language preference | §7.7 |
| Syllabus upload → editable draft → confirm | §7.1 (+ open question 4) |
| Topic tree with checkboxes and mastery | §7.2 |
| Streaming tutor chat, scoped to a sub-topic | §7.2, §11 |
| Mic in → voice out | §7.5 |
| Theory ladder with hints | §7.3 |
| Coding problems, sandbox results, teach-from-error | §7.4 |
| Strength / weakness report | §7.6 |
| Focus timer | §7.8 |
| Lesson / test / focus history | §7.2, §7.3, §7.8 (logging) |

Deliberately **not** built: streaks, daily-plan cards and activity heatmaps.
Those are Phase 2 in the PRD (§4, §13). The History page lists what was logged
rather than charting it — the visualisations themselves stay Phase 2.

### Enabling Google sign-in

The button only renders when `VITE_GOOGLE_CLIENT_ID` is set in `client/.env`.
Create an OAuth 2.0 Client ID (Web) at
<https://console.cloud.google.com/apis/credentials>, add `http://localhost:5173`
as an authorised JavaScript origin, then put the client ID in both
`client/.env` (`VITE_GOOGLE_CLIENT_ID`) and `server/.env` (`GOOGLE_CLIENT_ID`,
so the backend verifies the token's audience).

### Endpoints intentionally left unused

`teach.send`, `teach.session`, `subjects.replaceTree`, `voice.chat` and
`voice.languages` exist in `lib/api.js` but no component calls them — each is a
narrower or redundant variant of something the UI already uses (streaming
instead of one-shot teaching, per-node tree edits instead of a bulk replace,
and `/voice/transcribe` + `/voice/speak` instead of the combined
`/voice/chat`, so speech and typing share one code path).

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
- **Voice reuses the text path.** The mic records, posts to `/voice/transcribe`,
  and the resulting text goes through the same streaming turn as typing. The
  transcript is shown as the student's message, so a Whisper mishearing is
  visible rather than mysterious. The reply is then read aloud via
  `/voice/speak` when spoken replies are on.
- **Voice degrades to text.** If TTS fails for a language the backend returns
  `voice_enabled: false` and the UI shows a note instead of failing silently.
- **A retake needs `subtopic_id`**, which the summary payload doesn't carry, so
  it is passed through router state. Deep-linking to a finished attempt hides
  the retake button rather than showing a broken one.

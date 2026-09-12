# Padhlo — AI Smart Study Companion

Turn a syllabus into a study tree, learn each sub-topic with a tutor that
teaches step by step, then test yourself with assessments that adapt to your
answers.

- **Backend** — FastAPI + PostgreSQL/pgvector · [`server/`](server/README.md)
- **Frontend** — React + Vite · [`client/`](client/README.md)
- **Spec** — [AI-Smart-Study-Companion-PRD.md](server/AI-Smart-Study-Companion-PRD.md)

---

## Run it

From **anywhere in the repo**:

```bash
npm run setup     # first time only
npm run dev       # starts the database, backend and frontend together
```

Then open **http://localhost:5173**.

`Ctrl+C` stops everything. If one process dies, the other is shut down too, so
you never end up with a half-running stack.

### All commands

| Command | What it does |
|---|---|
| `npm run dev` | Database + backend + frontend, with prefixed output |
| `npm run dev:api` | Backend only (port 8000) |
| `npm run dev:web` | Frontend only (port 5173) |
| `npm run stop` | Frees ports 8000 and 5173 |
| `npm run setup` | Virtualenv, dependencies, `.env` files, migrations, sandbox image |
| `npm run db:up` / `db:down` | Just the Postgres container |
| `npm test` | Every test suite |
| `npm run build` | Production build of the frontend |
| `npm run lint` | Lint the frontend |

`npm run dev -- --no-db` skips starting the database, if you run Postgres
yourself.

---

## If something won't start

**Port already in use** — usually a previous run that wasn't closed with
`Ctrl+C`. On Windows this shows up as the unhelpful
`WinError 10013: socket access forbidden`. `npm run dev` now names the process
holding the port; free it with:

```bash
npm run stop
```

**`ModuleNotFoundError` from the backend** — a bare `uvicorn` picks up whatever
is first on PATH, which may be a global install without this project's
dependencies. `npm run dev` always uses `server/.venv`, so prefer it over
calling `uvicorn` directly.

**Database errors** — Docker Desktop needs to be running. `npm run dev` warns
you if it isn't, rather than failing with a connection error later.

**AI features return a "having trouble" message** — add your keys to
`server/.env`:

```
GEMINI_API_KEY=...   # https://aistudio.google.com/app/apikey
GROQ_API_KEY=...     # https://console.groq.com/keys  (also powers speech-to-text)
```

Check everything at once with **http://127.0.0.1:8000/health/full** — it reports
the database, both AI providers, the code sandbox and voice.

---

## Tests

```bash
npm test                  # everything
npm run test:contract     # frontend/backend API contract (needs the backend up)
```

| Suite | Needs | Covers |
|---|---|---|
| `server/scripts/test_engine.py` | nothing | Adaptive ladder, mastery decay, grading, syllabus parsing |
| `server/scripts/test_sandbox.py` | Docker | Code execution, network isolation, timeouts |
| `server/scripts/smoke_test.py` | backend | Full API flow |
| `server/scripts/test_features.py` | backend + keys | Syllabus parsing, streaming, coding loop, voice |
| `client/scripts/contract-test.mjs` | backend | Every field the UI reads actually exists |

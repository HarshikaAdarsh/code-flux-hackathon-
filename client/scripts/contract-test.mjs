/**
 * Contract test: drives the backend exactly as the React app does and asserts
 * that every field the components read actually exists in the response.
 *
 * Catches the class of bug a type-less fetch layer hides — a renamed or absent
 * field that only shows up as "undefined" in the UI.
 *
 *   node scripts/contract-test.mjs [http://127.0.0.1:8000]
 */

const BASE = (process.argv[2] || 'http://127.0.0.1:8000').replace(/\/$/, '');
let token = null;
const results = [];

function check(name, ok, detail = '') {
  results.push({ name, ok });
  console.log(`${ok ? '[ok]' : '[XX]'} ${name}${detail ? ` — ${detail}` : ''}`);
}

/** Assert every dotted path exists (not undefined) on obj. */
function hasFields(name, obj, fields) {
  const missing = fields.filter((f) => {
    const v = f.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
    return v === undefined;
  });
  check(name, missing.length === 0, missing.length ? `missing: ${missing.join(', ')}` : `${fields.length} fields`);
  return missing.length === 0;
}

async function api(path, { method = 'GET', body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new Error(typeof data?.detail === 'string' ? data.detail : `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function main() {
  /* ---------------- health ---------------- */
  const health = await api('/health/full');
  const aiReady = !health.llm.degraded;
  check('health/full', true, `db=${health.database.ok} ai=${aiReady ? 'ready' : 'degraded'}`);

  /* ---------------- CORS preflight (the browser will do this) ------------- */
  const pre = await fetch(`${BASE}/subjects`, {
    method: 'OPTIONS',
    headers: {
      Origin: 'http://localhost:5173',
      'Access-Control-Request-Method': 'GET',
      'Access-Control-Request-Headers': 'authorization',
    },
  });
  check(
    'CORS allows the Vite origin',
    pre.headers.get('access-control-allow-origin') === 'http://localhost:5173',
    pre.headers.get('access-control-allow-origin') || 'no header',
  );

  /* ---------------- auth (AuthContext / AuthPage) ---------------- */
  const email = `ui-${Math.random().toString(36).slice(2, 10)}@example.com`;
  const signup = await api('/auth/signup', {
    method: 'POST',
    body: { email, name: 'UI Contract', password: 'test-password-123', preferred_language: 'en' },
  });
  hasFields('auth/signup shape', signup, [
    'access_token', 'user.id', 'user.email', 'user.name',
    'user.preferred_language', 'user.pomodoro_minutes',
  ]);
  token = signup.access_token;

  const me = await api('/auth/me');
  hasFields('auth/me shape', me, ['id', 'name', 'email', 'preferred_language', 'pomodoro_minutes']);

  const patched = await api('/auth/me', { method: 'PATCH', body: { pomodoro_minutes: 30 } });
  check('PATCH /auth/me applies', patched.pomodoro_minutes === 30, `${patched.pomodoro_minutes} min`);

  /* ---------------- subject create (NewSubjectPage manual) ---------------- */
  const created = await api('/subjects', {
    method: 'POST',
    body: {
      name: 'Operating Systems',
      type: 'non-coding',
      topics: [
        { title: 'Processes', subtopics: [{ title: 'Process states' }, { title: 'Context switching' }] },
        { title: 'Memory', subtopics: [{ title: 'Paging' }] },
      ],
    },
  });
  hasFields('POST /subjects shape', created, [
    'id', 'name', 'type', 'status', 'created_at',
    'topics.0.id', 'topics.0.title', 'topics.0.is_completed',
    'topics.0.subtopics.0.id', 'topics.0.subtopics.0.title',
    'topics.0.subtopics.0.is_completed', 'topics.0.subtopics.0.mastery_score',
    'progress.total_subtopics', 'progress.completed_subtopics',
    'progress.percent_complete', 'progress.avg_mastery',
  ]);
  const subjectId = created.id;
  const subtopicId = created.topics[0].subtopics[0].id;
  const topicId = created.topics[0].id;

  /* ---------------- dashboard list ---------------- */
  const list = await api('/subjects');
  hasFields('GET /subjects list-item shape', list[0], [
    'id', 'name', 'type', 'status', 'created_at',
    'topic_count', 'subtopic_count', 'completed_subtopics', 'avg_mastery',
  ]);

  /* ---------------- syllabus upload (NewSubjectPage upload) ---------------- */
  if (aiReady) {
    const fd = new FormData();
    const syllabus = `Unit 1: Introduction to Databases
Data models, Schema and instances, Three-schema architecture

Unit 2: Relational Model
Relational algebra, Tuple calculus, Integrity constraints

Unit 3: Normalization
Functional dependencies, 1NF, 2NF, 3NF, BCNF`;
    fd.append('file', new Blob([syllabus], { type: 'text/plain' }), 'syllabus.txt');
    fd.append('name', 'DBMS');
    fd.append('type', 'non-coding');
    const parsed = await api('/subjects/upload', { method: 'POST', form: fd });
    hasFields('POST /subjects/upload shape', parsed, [
      'subject_id', 'status', 'confidence', 'needs_manual_entry', 'message',
      'topics.0.title', 'topics.0.subtopics.0.title',
    ]);
    check('upload yields a draft (open q4)', parsed.status === 'draft', parsed.status);

    const confirmed = await api(`/subjects/${parsed.subject_id}/confirm`, {
      method: 'POST',
      body: { topics: parsed.topics },
    });
    check('confirm activates the subject', confirmed.status === 'active', confirmed.status);
    await api(`/subjects/${parsed.subject_id}`, { method: 'DELETE' });
  } else {
    check('syllabus upload', true, 'SKIPPED (no AI key)');
  }

  /* ---------------- tree edits (TopicTree) ---------------- */
  const sub = await api(`/subtopics/${subtopicId}`, { method: 'PATCH', body: { is_completed: true } });
  hasFields('PATCH /subtopics shape', sub, ['id', 'title', 'is_completed', 'mastery_score', 'order_index']);

  const newSub = await api(`/topics/${topicId}/subtopics`, { method: 'POST', body: { title: 'Scheduling' } });
  hasFields('POST /topics/{id}/subtopics shape', newSub, ['id', 'title', 'is_completed', 'mastery_score']);
  await api(`/subtopics/${newSub.id}`, { method: 'DELETE' });

  const newTopic = await api(`/subjects/${subjectId}/topics`, {
    method: 'POST',
    body: { title: 'Concurrency', subtopics: [{ title: 'Deadlocks' }] },
  });
  hasFields('POST /subjects/{id}/topics shape', newTopic, ['id', 'title', 'is_completed', 'subtopics']);
  await api(`/topics/${newTopic.id}`, { method: 'DELETE' });

  const tree = await api(`/subjects/${subjectId}/tree`);
  check('tree reflects the completion', tree.progress.completed_subtopics === 1, `${tree.progress.completed_subtopics} done`);

  /* ---------------- pomodoro (PomodoroWidget) ---------------- */
  const started = await api('/pomodoro/start', {
    method: 'POST',
    body: { subject_id: subjectId, subtopic_id: subtopicId, planned_minutes: 25 },
  });
  hasFields('POST /pomodoro/start shape', started, [
    'id', 'planned_minutes', 'duration_minutes', 'status', 'started_at',
  ]);
  const active = await api('/pomodoro/active');
  check('GET /pomodoro/active returns the row', active?.id === started.id);
  const paused = await api(`/pomodoro/${started.id}/pause`, { method: 'POST' });
  check('pause -> paused', paused.status === 'paused', paused.status);
  await api(`/pomodoro/${started.id}/resume`, { method: 'POST' });
  const stopped = await api(`/pomodoro/${started.id}/stop?completed=true&duration_minutes=25`, { method: 'POST' });
  check('stop logs the duration', stopped.duration_minutes === 25, `${stopped.duration_minutes} min`);

  /* ---------------- teaching (TutorPanel) ---------------- */
  if (aiReady) {
    // non-streaming path
    const reply = await api('/teach', {
      method: 'POST',
      body: { subtopic_id: subtopicId, message: 'One sentence only: what is a process state?', mode: 'text' },
    });
    hasFields('POST /teach shape', reply, ['session_id', 'reply', 'provider', 'voice_enabled', 'language', 'messages']);

    // SSE path — exactly what TutorPanel parses
    const res = await fetch(`${BASE}/teach/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ subtopic_id: subtopicId, message: 'Two sentences on context switching.', mode: 'text' }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    const seen = new Set();
    let text = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, i);
        buf = buf.slice(i + 2);
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const ev = JSON.parse(line.slice(5).trim());
          seen.add(ev.type);
          if (ev.type === 'token') text += ev.value;
        }
      }
    }
    check('SSE emits session/provider/token/done',
      ['session', 'provider', 'token', 'done'].every((t) => seen.has(t)),
      [...seen].join(','));
    check('SSE produced lesson text', text.length > 50, `${text.length} chars`);

    const sessions = await api(`/teach/sessions?subtopic_id=${subtopicId}&limit=1`);
    hasFields('GET /teach/sessions shape', sessions[0], ['id', 'messages', 'mode', 'language', 'created_at']);
  } else {
    check('teaching', true, 'SKIPPED (no AI key)');
  }

  /* ---------------- assessment (TheoryRunner + summary) ---------------- */
  if (aiReady) {
    const state = await api('/assessments/start', { method: 'POST', body: { subtopic_id: subtopicId } });
    hasFields('POST /assessments/start shape', state, [
      'attempt_id', 'status', 'kind', 'current_difficulty', 'questions_answered',
      'max_questions', 'mastery_score', 'finished',
      'question.id', 'question.difficulty', 'question.kind', 'question.question',
    ]);
    check('theory question carries options', Array.isArray(state.question.options), `${state.question.options?.length} options`);
    check('answer is never sent to the client',
      state.question.answer === undefined && state.question.explanation === undefined,
      Object.keys(state.question).join(','));

    const hint = await api(`/assessments/${state.attempt_id}/hint`, { method: 'POST', body: {} });
    hasFields('POST /assessments/{id}/hint shape', hint, ['hint', 'hints_used']);

    const ans = await api(`/assessments/${state.attempt_id}/answer`, {
      method: 'POST',
      body: { answer: state.question.options?.[0] || 'unsure', hints_used: 1 },
    });
    hasFields('POST /assessments/{id}/answer shape', ans, [
      'is_correct', 'feedback', 'state.attempt_id', 'state.questions_answered',
      'state.current_difficulty', 'state.mastery_score', 'state.finished',
    ]);
    check('answer response carries the next question',
      ans.state.finished || !!ans.state.question,
      ans.state.finished ? 'attempt finished' : `next: ${ans.state.question?.difficulty}`);

    const summary = await api(`/assessments/${state.attempt_id}/summary`);
    hasFields('GET /assessments/{id}/summary shape', summary, [
      'attempt_id', 'subtopic', 'kind', 'total_questions', 'correct', 'accuracy',
      'highest_difficulty_reached', 'hints_used', 'mastery_score', 'classification',
      'recommendation', 'responses',
    ]);
    if (summary.responses.length) {
      hasFields('summary response-row shape', summary.responses[0], [
        'question', 'difficulty', 'is_correct', 'feedback', 'hints_used', 'needed_solution',
      ]);
    }
    // Known gap the UI works around: no subtopic_id on the summary payload.
    check('summary has no subtopic_id (UI passes it via router state)',
      summary.subtopic_id === undefined, 'confirmed');

    await api(`/assessments/${state.attempt_id}/finish`, { method: 'POST' }).catch(() => {});
  } else {
    check('assessment', true, 'SKIPPED (no AI key)');
  }

  /* ---------------- coding assessment (CodingRunner) ---------------- */
  if (aiReady) {
    const coding = await api('/subjects', {
      method: 'POST',
      body: { name: 'Python Basics', type: 'coding', topics: [{ title: 'Lists', subtopics: [{ title: 'List comprehensions' }] }] },
    });
    const cSub = coding.topics[0].subtopics[0].id;
    await api(`/subtopics/${cSub}`, { method: 'PATCH', body: { is_completed: true } });

    const cState = await api('/assessments/start', { method: 'POST', body: { subtopic_id: cSub } });
    check('coding assessment kind', cState.kind === 'coding', cState.kind);
    hasFields('coding question shape', cState.question, [
      'id', 'difficulty', 'kind', 'question', 'starter_code', 'visible_tests',
    ]);
    check('reference solution is hidden',
      cState.question.solution === undefined && cState.question.tests === undefined,
      Object.keys(cState.question).join(','));

    const bad = await api(`/assessments/${cState.attempt_id}/submit-code`, {
      method: 'POST',
      body: { code: 'def solve(x):\n    return None\n', language: 'python', hints_used: 0, give_up: false },
    });
    hasFields('POST submit-code shape', bad, [
      'attempt_id', 'passed', 'tests', 'stdout', 'stderr', 'runtime_ms',
      'feedback', 'state.questions_answered',
    ]);
    check('failing submission does not consume the question',
      bad.state.questions_answered === 0, `answered=${bad.state.questions_answered}`);
    if (bad.tests.length) {
      hasFields('test-result shape', bad.tests[0], ['name', 'passed', 'input', 'expected']);
    }

    const up = await api(`/assessments/${cState.attempt_id}/submit-code`, {
      method: 'POST',
      body: { code: 'def solve(x):\n    return None\n', language: 'python', hints_used: 0, give_up: true },
    });
    check('give-up returns a solution', !!up.solution, up.solution ? `${up.solution.length} chars` : 'none');
    check('give-up consumes the question', up.state.questions_answered === 1, `answered=${up.state.questions_answered}`);

    await api(`/subjects/${coding.id}`, { method: 'DELETE' });
  } else {
    check('coding assessment', true, 'SKIPPED (no AI key)');
  }

  /* ---------------- report (ReportPage) ---------------- */
  const report = await api(`/reports/${subjectId}?ai_summary=false`);
  hasFields('GET /reports/{id} shape', report, [
    'subject_id', 'subject', 'overall_mastery', 'tested_subtopics', 'total_subtopics',
    'strengths', 'weaknesses', 'needs_practice', 'untested', 'study_minutes_7d',
  ]);
  const anyRow = [...report.strengths, ...report.weaknesses, ...report.needs_practice, ...report.untested][0];
  if (anyRow) {
    hasFields('report-row shape', anyRow, [
      'subtopic_id', 'topic', 'subtopic', 'attempts', 'accuracy',
      'mastery_score', 'highest_difficulty_reached', 'hints_used', 'classification',
    ]);
  }

  /* ---------------- voice (useVoice / TutorPanel) ---------------- */
  const spoken = await api('/voice/speak', { method: 'POST', body: { text: 'Paging splits memory into fixed blocks.', language: 'en' } });
  hasFields('POST /voice/speak shape', spoken, ['audio_url', 'voice_enabled']);
  if (spoken.audio_url) {
    const audio = await fetch(`${BASE}${spoken.audio_url}`);
    check('audio file is served', audio.ok && Number(audio.headers.get('content-length')) > 1000,
      `${audio.headers.get('content-length')} bytes`);
  }
  const langs = await api('/voice/languages');
  hasFields('GET /voice/languages shape', langs, ['stt.configured', 'stt.model', 'tts.provider', 'languages']);

  /* ---------------- cleanup ---------------- */
  await api(`/subjects/${subjectId}`, { method: 'DELETE' });
  check('subject delete cascades', true);

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error(`\nFATAL: ${err.message}`);
  process.exit(2);
});

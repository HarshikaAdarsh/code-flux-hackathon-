import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  assessments as assessApi,
  pomodoro as pomodoroApi,
  subjects as subjectsApi,
  teach as teachApi,
} from '../lib/api';
import { useToast } from '../context/ToastContext';
import { useChrome } from '../lib/useChrome';
import Markdown from '../components/Markdown';
import Modal from '../components/Modal';
import { CLASSIFICATION_LABEL, DIFFICULTY_LABEL, masteryColor } from '../lib/format';
import { Brain, Check, Cross, Doc, Timer, Trash } from '../lib/icons';

const TABS = [
  { key: 'lessons', label: 'Lessons' },
  { key: 'tests', label: 'Tests' },
  { key: 'focus', label: 'Focus sessions' },
];

function when(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export default function HistoryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [tab, setTab] = useState('lessons');
  const [tree, setTree] = useState(null);
  const [lessons, setLessons] = useState(null);
  const [attempts, setAttempts] = useState(null);
  const [focus, setFocus] = useState(null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState('');
  const [openLesson, setOpenLesson] = useState(null);

  const load = useCallback(async () => {
    const [treeData, lessonRows, attemptRows, focusRows, statRow] = await Promise.all([
      subjectsApi.tree(id),
      teachApi.sessions({ subject_id: id, limit: 100 }),
      assessApi.list({ limit: 100 }),
      pomodoroApi.sessions(100),
      pomodoroApi.stats(90),
    ]);
    setTree(treeData);
    setLessons(lessonRows);
    setAttempts(attemptRows);
    setFocus(focusRows);
    setStats(statRow);
  }, [id]);

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [load]);

  useChrome(
    <>
      <Link to={`/subjects/${id}`}>{tree?.name || 'Subject'}</Link>
      <span>/</span>
      <span className="now">History</span>
    </>,
    { subjectId: id },
    [tree?.name, id],
  );

  /** sub-topic id -> {title, topic} so history rows can name themselves. */
  const titles = useMemo(() => {
    const map = new Map();
    for (const t of tree?.topics || []) {
      for (const s of t.subtopics) map.set(s.id, { title: s.title, topic: t.title });
    }
    return map;
  }, [tree]);

  // The attempts endpoint is user-wide; keep only this subject's sub-topics.
  const subjectAttempts = useMemo(
    () => (attempts || []).filter((a) => titles.has(a.subtopic_id)),
    [attempts, titles],
  );
  const subjectFocus = useMemo(
    () => (focus || []).filter((f) => f.subject_id === id),
    [focus, id],
  );

  async function deleteLesson(sessionId) {
    if (!window.confirm('Delete this lesson transcript? The tutor will start fresh on that sub-topic.')) return;
    try {
      await teachApi.removeSession(sessionId);
      setLessons((rows) => rows.filter((r) => r.id !== sessionId));
      toast.success('Transcript deleted.');
    } catch (err) {
      toast.error(err);
    }
  }

  async function retest(subtopicId, title) {
    try {
      const state = await assessApi.start({ subtopic_id: subtopicId });
      navigate(`/assessments/${state.attempt_id}`, {
        state: { subjectId: id, subtopicId, subtopicTitle: title },
      });
    } catch (err) {
      toast.error(err);
    }
  }

  if (error) {
    return (
      <div className="center-pad">
        <h2>Couldn&apos;t load history</h2>
        <p className="muted">{error}</p>
        <Link className="btn btn-ghost" to={`/subjects/${id}`}>Back to syllabus</Link>
      </div>
    );
  }

  if (!tree) {
    return (
      <div className="center-pad">
        <span className="spinner lg" />
        <p className="muted">Loading your history…</p>
      </div>
    );
  }

  const focusMinutes = subjectFocus.reduce((n, f) => n + (f.duration_minutes || 0), 0);

  return (
    <>
      <section className="band">
        <div className="wrap">
          <p className="band-meta">History</p>
          <h1 className="band-title">{tree.name}</h1>
          <div className="stats-strip">
            <div>
              <span className="stat-num">{lessons?.length ?? '–'}</span>
              <span className="stat-label">Lessons</span>
            </div>
            <div>
              <span className="stat-num">{subjectAttempts.length}</span>
              <span className="stat-label">Tests taken</span>
            </div>
            <div>
              <span className="stat-num">{focusMinutes}</span>
              <span className="stat-label">Focus minutes</span>
            </div>
            <div>
              <span className="stat-num">{stats?.total_minutes ?? 0}</span>
              <span className="stat-label">All subjects, min</span>
            </div>
          </div>
        </div>
      </section>

      <section className="wrap section">
        <div className="seg" style={{ marginBottom: 18 }}>
          {TABS.map((t) => (
            <button key={t.key} type="button" aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ---------------- lessons ---------------- */}
        {tab === 'lessons' && (
          lessons?.length ? (
            <ul className="history">
              {lessons.map((l) => {
                const info = titles.get(l.subtopic_id);
                const turns = (l.messages || []).length;
                return (
                  <li className="history-row" key={l.id}>
                    <span className="history-icon"><Doc /></span>
                    <div className="history-body">
                      <p className="history-title">{info?.title || l.title || 'Lesson'}</p>
                      <p className="history-meta">
                        {info?.topic ? `${info.topic} · ` : ''}
                        {turns} message{turns === 1 ? '' : 's'} · {l.mode === 'voice' ? 'voice' : 'text'} · {when(l.created_at)}
                      </p>
                    </div>
                    <div className="history-actions">
                      <button className="btn btn-ghost btn-sm" onClick={() => setOpenLesson(l)} type="button">
                        Read
                      </button>
                      {l.subtopic_id && (
                        <Link className="btn btn-ghost btn-sm" to={`/subjects/${id}?subtopic=${l.subtopic_id}`}>
                          Continue
                        </Link>
                      )}
                      <button className="tool danger" onClick={() => deleteLesson(l.id)} title="Delete transcript" type="button">
                        <Trash />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="empty">
              <h3>No lessons yet</h3>
              <p>Pick a sub-topic and start a lesson — the transcript is saved here.</p>
            </div>
          )
        )}

        {/* ---------------- tests ---------------- */}
        {tab === 'tests' && (
          subjectAttempts.length ? (
            <ul className="history">
              {subjectAttempts.map((a) => {
                const info = titles.get(a.subtopic_id);
                const done = a.status !== 'in_progress';
                return (
                  <li className="history-row" key={a.attempt_id}>
                    <span className={`history-icon ${a.classification || ''}`}><Brain /></span>
                    <div className="history-body">
                      <p className="history-title">{info?.title || 'Sub-topic'}</p>
                      <p className="history-meta">
                        {a.kind === 'coding' ? 'Coding' : 'Theory'} · {a.questions_answered} answered ·
                        {' '}reached {DIFFICULTY_LABEL[a.highest_difficulty_reached] || a.highest_difficulty_reached} ·
                        {' '}{when(a.started_at)}
                        {!done && ' · in progress'}
                      </p>
                    </div>
                    <div className="history-actions">
                      {a.classification && (
                        <span className={`verdict ${a.classification}`}>
                          {CLASSIFICATION_LABEL[a.classification]}
                        </span>
                      )}
                      {a.final_mastery_score != null && (
                        <span className="mono" style={{ color: masteryColor(a.final_mastery_score), fontWeight: 700 }}>
                          {a.final_mastery_score}
                        </span>
                      )}
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={`/assessments/${a.attempt_id}`}
                        state={{ subjectId: id, subtopicId: a.subtopic_id, subtopicTitle: info?.title }}
                      >
                        {done ? 'Results' : 'Resume'}
                      </Link>
                      {done && info && (
                        <button className="btn btn-ghost btn-sm" onClick={() => retest(a.subtopic_id, info.title)} type="button">
                          Retest
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="empty">
              <h3>No tests yet</h3>
              <p>Tick a sub-topic as done, then test yourself on it.</p>
            </div>
          )
        )}

        {/* ---------------- focus ---------------- */}
        {tab === 'focus' && (
          subjectFocus.length ? (
            <ul className="history">
              {subjectFocus.map((f) => (
                <li className="history-row" key={f.id}>
                  <span className={`history-icon ${f.status === 'completed' ? 'strength' : ''}`}><Timer /></span>
                  <div className="history-body">
                    <p className="history-title">
                      {f.duration_minutes} min
                      {f.subtopic_id && titles.get(f.subtopic_id) ? ` · ${titles.get(f.subtopic_id).title}` : ''}
                    </p>
                    <p className="history-meta">
                      planned {f.planned_minutes} min · {when(f.started_at)}
                    </p>
                  </div>
                  <div className="history-actions">
                    <span className={`badge ${f.status === 'completed' ? 'badge-green' : ''}`}>
                      {f.status === 'completed' ? <Check /> : <Cross />}
                      {f.status === 'completed' ? 'Completed' : f.status}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty">
              <h3>No focus sessions yet</h3>
              <p>Start the timer in the top bar while you study this subject.</p>
            </div>
          )
        )}
      </section>

      <Modal
        open={!!openLesson}
        onClose={() => setOpenLesson(null)}
        title={titles.get(openLesson?.subtopic_id)?.title || openLesson?.title || 'Lesson'}
        hint={`${(openLesson?.messages || []).length} messages`}
        wide
        actions={<button className="btn btn-ghost" onClick={() => setOpenLesson(null)} type="button">Close</button>}
      >
        <div className="transcript-replay">
          {(openLesson?.messages || []).map((m, i) =>
            m.role === 'user' ? (
              <div className="msg user" key={i}>{m.content}</div>
            ) : (
              <div className="msg tutor" key={i}><Markdown>{m.content}</Markdown></div>
            ),
          )}
        </div>
      </Modal>

      <section className="wrap section">
        <Link className="btn btn-ghost" to={`/subjects/${id}`}>Back to syllabus</Link>
      </section>
    </>
  );
}

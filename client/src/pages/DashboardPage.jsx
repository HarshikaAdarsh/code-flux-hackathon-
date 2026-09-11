import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { subjects as subjectsApi } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { greeting, pct, spineColor, today } from '../lib/format';
import { Arrow, CubeBook, CubeChat, CubeCheck, Plus } from '../lib/icons';

function SubjectCard({ s }) {
  const spine = spineColor(s.id);
  const percent = pct(s.completed_subtopics, s.subtopic_count);
  return (
    <Link className="subject" to={`/subjects/${s.id}`} style={{ '--spine': spine }}>
      <span className="subject-top">
        <span className="subject-type">
          {s.type === 'coding' ? 'Coding' : 'Theory'}
          {s.status === 'draft' ? ' · draft' : ''}
        </span>
        <span className="arrow-chip"><Arrow /></span>
      </span>
      <span className="subject-name">{s.name}</span>
      <span className="muted" style={{ fontSize: 13 }}>
        {s.topic_count} topics · {s.subtopic_count} sub-topics
      </span>
      <span className="subject-foot">
        <span className="bar"><span style={{ width: `${percent}%` }} /></span>
        {s.completed_subtopics} of {s.subtopic_count} done
      </span>
      <span className="muted" style={{ fontSize: 12.5 }}>
        Avg mastery {s.avg_mastery}/100
      </span>
    </Link>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [list, setList] = useState(null);

  useEffect(() => {
    let alive = true;
    subjectsApi
      .list()
      .then((rows) => alive && setList(rows))
      .catch((err) => {
        if (alive) {
          setList([]);
          toast.error(err);
        }
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totals = (list || []).reduce(
    (acc, s) => ({
      subtopics: acc.subtopics + s.subtopic_count,
      done: acc.done + s.completed_subtopics,
      mastery: acc.mastery + s.avg_mastery,
    }),
    { subtopics: 0, done: 0, mastery: 0 },
  );
  const avgMastery = list?.length ? Math.round(totals.mastery / list.length) : 0;

  // A draft subject still needs its AI-parsed tree confirmed (PRD 7.1).
  const drafts = (list || []).filter((s) => s.status === 'draft');

  return (
    <>
      <section className="band hero">
        <div className="wrap">
          <div className="hero-blocks" aria-hidden="true">
            <div className="cube cube-a"><CubeBook /></div>
            <div className="cube cube-b"><CubeChat /></div>
            <div className="cube cube-c"><CubeCheck /></div>
            <span className="hexdot hexdot-a" />
            <span className="hexdot hexdot-b" />
          </div>
          <p className="hero-kicker">{today()}</p>
          <h1 className="hero-title">
            {greeting()}, {user?.name?.split(' ')[0] || 'there'}.
          </h1>
          <p className="hero-sub">
            Pick a subject, study a sub-topic with the tutor, tick it off, then test yourself.
          </p>
          <div className="stats-strip">
            <div>
              <span className="stat-num">{list?.length ?? '–'}</span>
              <span className="stat-label">Subjects</span>
            </div>
            <div>
              <span className="stat-num">{totals.done}/{totals.subtopics}</span>
              <span className="stat-label">Sub-topics done</span>
            </div>
            <div>
              <span className="stat-num">{avgMastery}</span>
              <span className="stat-label">Avg mastery</span>
            </div>
          </div>
        </div>
      </section>

      {drafts.length > 0 && (
        <section className="wrap" style={{ paddingTop: 24 }}>
          <div className="recommend">
            <h3>{drafts.length === 1 ? 'One subject is waiting for you' : `${drafts.length} subjects are waiting for you`}</h3>
            <p style={{ marginBottom: 12 }}>
              We parsed the syllabus but nothing is saved to the tree until you review and
              confirm it.
            </p>
            <div className="row gap8" style={{ flexWrap: 'wrap' }}>
              {drafts.map((d) => (
                <button
                  key={d.id}
                  className="btn btn-ink btn-sm"
                  onClick={() => navigate(`/subjects/${d.id}`)}
                >
                  Review “{d.name}”
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="wrap section">
        <div className="section-head">
          <h2>Your subjects</h2>
          {list && <span className="muted">{list.length} total</span>}
        </div>

        {!list ? (
          <div className="center-pad">
            <span className="spinner lg" />
            <p className="muted">Loading your subjects…</p>
          </div>
        ) : (
          <div className="subject-grid">
            {list.map((s) => (
              <SubjectCard key={s.id} s={s} />
            ))}
            <Link className="subject subject-add" to="/subjects/new">
              <Plus style={{ width: 20, height: 20 }} />
              Add a subject
            </Link>
          </div>
        )}

        {list && list.length === 0 && (
          <div className="empty">
            <h3>No subjects yet</h3>
            <p>Upload a syllabus PDF and we&apos;ll turn it into a study tree, or add topics by hand.</p>
          </div>
        )}
      </section>
    </>
  );
}

import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { assessments as assessApi, reports as reportsApi } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useChrome } from '../lib/useChrome';
import { CLASSIFICATION_LABEL, DIFFICULTY_LABEL, masteryColor } from '../lib/format';
import { Brain } from '../lib/icons';

const ORDER = ['weakness', 'needs_practice', 'strength', 'untested'];
const BUCKET_KEY = {
  weakness: 'weaknesses',
  needs_practice: 'needs_practice',
  strength: 'strengths',
  untested: 'untested',
};

function Row({ r, onAssess }) {
  return (
    <div className="report-row">
      <p className="t">{r.topic}</p>
      <p className="n">{r.subtopic}</p>
      <div className="m">
        <span className="bar">
          <span style={{ width: `${r.mastery_score}%`, background: masteryColor(r.mastery_score) }} />
        </span>
        <span className="mono">{r.mastery_score}</span>
        {r.attempts > 0 && (
          <span>
            {Math.round(r.accuracy * 100)}% · reached{' '}
            {DIFFICULTY_LABEL[r.highest_difficulty_reached] || r.highest_difficulty_reached}
          </span>
        )}
      </div>
      {r.classification !== 'untested' && (
        <div className="row gap8" style={{ marginTop: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => onAssess(r)} type="button">
            <Brain style={{ width: 13, height: 13 }} />
            Retest
          </button>
          {r.hints_used > 0 && <span className="badge badge-gold">{r.hints_used} hints</span>}
        </div>
      )}
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { language } = useAuth();
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');

  useChrome(
    <>
      <Link to={`/subjects/${id}`}>{report?.subject || 'Subject'}</Link>
      <span>/</span>
      <span className="now">Report</span>
    </>,
    { subjectId: id },
    [report?.subject, id],
  );

  useEffect(() => {
    let alive = true;
    reportsApi
      .subject(id)
      .then((r) => alive && setReport(r))
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [id]);

  async function assess(row) {
    try {
      const state = await assessApi.start({ subtopic_id: row.subtopic_id, language });
      navigate(`/assessments/${state.attempt_id}`, {
        state: { subjectId: id, subtopicId: row.subtopic_id, subtopicTitle: row.subtopic },
      });
    } catch (err) {
      toast.error(err);
    }
  }

  if (error) {
    return (
      <div className="center-pad">
        <h2>Couldn&apos;t load this report</h2>
        <p className="muted">{error}</p>
        <Link className="btn btn-ghost" to={`/subjects/${id}`}>Back to syllabus</Link>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="center-pad">
        <span className="spinner lg" />
        <p className="muted">Working out where you&apos;re strong…</p>
      </div>
    );
  }

  const nothingTested = report.tested_subtopics === 0;

  return (
    <>
      <section className="band">
        <div className="wrap">
          <p className="band-meta">Strengths &amp; weaknesses</p>
          <h1 className="band-title">{report.subject}</h1>
          <div className="stats-strip">
            <div>
              <span className="stat-num">{report.overall_mastery}</span>
              <span className="stat-label">Overall mastery</span>
            </div>
            <div>
              <span className="stat-num">{report.tested_subtopics}/{report.total_subtopics}</span>
              <span className="stat-label">Sub-topics tested</span>
            </div>
            <div>
              <span className="stat-num">{report.strengths.length}</span>
              <span className="stat-label">Strengths</span>
            </div>
            <div>
              <span className="stat-num">{report.weaknesses.length}</span>
              <span className="stat-label">Weak areas</span>
            </div>
            <div>
              <span className="stat-num">{report.study_minutes_7d}</span>
              <span className="stat-label">Focus min, 7d</span>
            </div>
          </div>
        </div>
      </section>

      <section className="wrap" style={{ paddingTop: 26 }}>
        {report.next_recommendation && (
          <div className="recommend">
            <h3>What to study next</h3>
            <p>{report.next_recommendation}</p>
          </div>
        )}
      </section>

      {nothingTested ? (
        <section className="wrap section">
          <div className="empty">
            <h3>Nothing tested yet</h3>
            <p>
              Study a sub-topic, tick it off, then run an assessment. This page fills in
              once you have answers to analyse.
            </p>
            <Link className="btn btn-marker" style={{ marginTop: 14 }} to={`/subjects/${id}`}>
              Go to syllabus
            </Link>
          </div>
        </section>
      ) : (
        <section className="wrap report-cols">
          {ORDER.map((kind) => {
            const rows = report[BUCKET_KEY[kind]] || [];
            if (!rows.length) return null;
            return (
              <div className={`report-col ${kind}`} key={kind}>
                <div className="report-col-head">
                  <h3>{CLASSIFICATION_LABEL[kind]}</h3>
                  <span className="badge">{rows.length}</span>
                </div>
                {rows.map((r) => (
                  <Row key={r.subtopic_id} r={r} onAssess={assess} />
                ))}
              </div>
            );
          })}
        </section>
      )}

      <section className="wrap section">
        <Link className="btn btn-ghost" to={`/subjects/${id}`}>Back to syllabus</Link>
      </section>
    </>
  );
}

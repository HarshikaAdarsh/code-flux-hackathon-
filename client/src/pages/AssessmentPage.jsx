import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { assessments as assessApi } from '../lib/api';
import { useToast } from '../context/ToastContext';
import { useChrome } from '../lib/useChrome';
import { DIFFICULTY_LABEL, pct } from '../lib/format';
import TheoryRunner from '../features/assessment/TheoryRunner';
import CodingRunner from '../features/assessment/CodingRunner';
import AttemptSummary from '../features/assessment/AttemptSummary';

export default function AssessmentPage() {
  const { attemptId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();

  const [state, setState] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');
  const [ending, setEnding] = useState(false);

  const subjectId = location.state?.subjectId;
  // The summary payload carries the sub-topic title but not its id, so a
  // retake is only offered when we still have it from the navigation state.
  const subtopicId = location.state?.subtopicId;
  const title = location.state?.subtopicTitle || summary?.subtopic || 'Assessment';

  useChrome(
    <>
      {subjectId ? <Link to={`/subjects/${subjectId}`}>Syllabus</Link> : <Link to="/">All subjects</Link>}
      <span>/</span>
      <span className="now">{title}</span>
    </>,
    { subjectId },
    [subjectId, title],
  );

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await assessApi.summary(attemptId));
    } catch (err) {
      setError(err.message);
    }
  }, [attemptId]);

  useEffect(() => {
    let alive = true;
    assessApi
      .get(attemptId)
      .then((s) => {
        if (!alive) return;
        if (s.finished) loadSummary();
        else setState(s);
      })
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [attemptId, loadSummary]);

  async function endEarly() {
    if (!window.confirm('End this assessment now? You will be scored on what you have answered.')) return;
    setEnding(true);
    try {
      setSummary(await assessApi.finish(attemptId));
      setState(null);
    } catch (err) {
      toast.error(err);
    } finally {
      setEnding(false);
    }
  }

  async function retake() {
    if (!subtopicId) return;
    try {
      const next = await assessApi.start({ subtopic_id: subtopicId });
      navigate(`/assessments/${next.attempt_id}`, {
        replace: true,
        state: { subjectId, subtopicId, subtopicTitle: summary.subtopic },
      });
      setSummary(null);
      setState(next);
    } catch (err) {
      toast.error(err);
    }
  }

  if (error) {
    return (
      <div className="center-pad">
        <h2>Couldn&apos;t load this assessment</h2>
        <p className="muted">{error}</p>
        <Link className="btn btn-ghost" to={subjectId ? `/subjects/${subjectId}` : '/'}>
          Back to syllabus
        </Link>
      </div>
    );
  }

  if (summary) {
    return (
      <>
        <section className="band">
          <div className="wrap">
            <p className="band-meta">Assessment complete</p>
            <h1 className="band-title">Results</h1>
          </div>
        </section>
        <AttemptSummary
          summary={summary}
          subjectId={subjectId}
          onRetake={subtopicId ? retake : null}
        />
      </>
    );
  }

  if (!state) {
    return (
      <div className="center-pad">
        <span className="spinner lg" />
        <p className="muted">Loading your assessment…</p>
      </div>
    );
  }

  const answered = state.questions_answered;
  const isCoding = state.kind === 'coding';

  return (
    <>
      <section className="band">
        <div className="wrap">
          <p className="band-meta">
            <span className="pill">{isCoding ? 'Coding' : 'Theory'}</span>
            <span>Adaptive · difficulty adjusts to your answers</span>
          </p>
          <h1 className="band-title">{title}</h1>
          <div className="assess-progress">
            <span className="bar thick">
              <span style={{ width: `${pct(answered, state.max_questions)}%` }} />
            </span>
            <span>
              {answered} of {state.max_questions} answered · now at{' '}
              {DIFFICULTY_LABEL[state.current_difficulty] || state.current_difficulty} · mastery{' '}
              {state.mastery_score}
            </span>
          </div>
          <div className="band-actions">
            <button className="btn btn-ghost" onClick={endEarly} disabled={ending} type="button">
              {ending ? 'Ending…' : 'End and score me'}
            </button>
          </div>
        </div>
      </section>

      <div className={`wrap assess${isCoding ? ' coding' : ''}`} style={!isCoding ? { maxWidth: 780 } : undefined}>
        {isCoding ? (
          <CodingRunner state={state} onState={setState} onFinished={loadSummary} />
        ) : (
          <TheoryRunner state={state} onState={setState} onFinished={loadSummary} />
        )}
      </div>
    </>
  );
}

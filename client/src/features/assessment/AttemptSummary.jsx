import { Link } from 'react-router-dom';
import Markdown from '../../components/Markdown';
import { CLASSIFICATION_LABEL, DIFFICULTY_LABEL, masteryColor } from '../../lib/format';
import { Check, Cross } from '../../lib/icons';

/** Results + mastery for one attempt (PRD 7.3 / 7.6). */
export default function AttemptSummary({ summary, subjectId, onRetake }) {
  const accuracy = Math.round((summary.accuracy || 0) * 100);

  return (
    <section className="wrap section" style={{ maxWidth: 780 }}>
      <div className="card card-hard">
        <div className="row gap12" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ fontSize: 22 }}>{summary.subtopic}</h2>
            <p className="muted">
              {summary.kind === 'coding' ? 'Coding assessment' : 'Theory assessment'} ·{' '}
              reached {DIFFICULTY_LABEL[summary.highest_difficulty_reached] || summary.highest_difficulty_reached}
            </p>
          </div>
          <span className={`verdict ${summary.classification}`}>
            {CLASSIFICATION_LABEL[summary.classification] || summary.classification}
          </span>
        </div>

        <div className="summary-grid">
          <div className="summary-tile">
            <div className="n">{summary.correct}/{summary.total_questions}</div>
            <div className="l">Correct</div>
          </div>
          <div className="summary-tile">
            <div className="n">{accuracy}%</div>
            <div className="l">Accuracy</div>
          </div>
          <div className="summary-tile">
            <div className="n" style={{ color: masteryColor(summary.mastery_score) }}>
              {summary.mastery_score}
            </div>
            <div className="l">Mastery</div>
          </div>
          <div className="summary-tile">
            <div className="n">{summary.hints_used}</div>
            <div className="l">Hints used</div>
          </div>
        </div>

        {summary.recommendation && (
          <div className="recommend">
            <h3>What to do next</h3>
            <p>{summary.recommendation}</p>
          </div>
        )}

        <div className="row gap8" style={{ marginTop: 18, flexWrap: 'wrap' }}>
          <Link className="btn btn-ink" to={`/subjects/${subjectId}`}>
            Back to syllabus
          </Link>
          <Link className="btn btn-ghost" to={`/subjects/${subjectId}/report`}>
            Full report
          </Link>
          {onRetake && (
            <button className="btn btn-ghost" onClick={onRetake} type="button">
              Test again
            </button>
          )}
        </div>
      </div>

      {summary.responses?.length > 0 && (
        <div className="review">
          <h3 style={{ fontSize: 17, margin: '24px 0 12px' }}>Question by question</h3>
          {summary.responses.map((r, i) => (
            <div className={`review-item ${r.is_correct ? 'ok' : 'no'}`} key={i}>
              <div className="review-meta">
                <span className={`pill pill-${r.difficulty}`}>{DIFFICULTY_LABEL[r.difficulty] || r.difficulty}</span>
                <span className={`badge ${r.is_correct ? 'badge-green' : 'badge-red'}`}>
                  {r.is_correct ? <Check /> : <Cross />}
                  {r.is_correct ? 'Correct' : 'Missed'}
                </span>
                {r.hints_used > 0 && <span className="badge badge-gold">{r.hints_used} hint{r.hints_used > 1 ? 's' : ''}</span>}
                {r.needed_solution && <span className="badge badge-red">Saw the solution</span>}
              </div>
              <p className="review-q">{r.question}</p>
              {r.feedback && <Markdown>{r.feedback}</Markdown>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

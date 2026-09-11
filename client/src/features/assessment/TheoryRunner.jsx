import { useEffect, useRef, useState } from 'react';
import { assessments as assessApi } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import Markdown from '../../components/Markdown';
import { DIFFICULTY_LABEL } from '../../lib/format';
import { Bulb, Check, Cross } from '../../lib/icons';

const KEY = ['A', 'B', 'C', 'D', 'E', 'F'];

/**
 * Theory ladder (PRD 7.3). The server owns the adaptive logic — each answer
 * comes back with the next question already chosen, so the client just renders
 * whatever state it is handed.
 */
export default function TheoryRunner({ state, onState, onFinished }) {
  const toast = useToast();
  const [choice, setChoice] = useState('');
  const [text, setText] = useState('');
  const [result, setResult] = useState(null); // {is_correct, correct_answer, feedback}
  const [nextState, setNextState] = useState(null);
  const [hint, setHint] = useState(null);
  const [hintsUsed, setHintsUsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const topRef = useRef(null);

  const q = state.question;

  // Fresh question -> clear everything from the previous one.
  useEffect(() => {
    setChoice('');
    setText('');
    setResult(null);
    setNextState(null);
    setHint(null);
    setHintsUsed(0);
    topRef.current?.scrollIntoView({ block: 'nearest' });
  }, [q?.id]);

  if (!q) return null;

  const answerValue = q.options?.length ? choice : text.trim();

  async function submit() {
    if (!answerValue || busy) return;
    setBusy(true);
    try {
      const res = await assessApi.answer(state.attempt_id, {
        answer: answerValue,
        hints_used: hintsUsed,
      });
      setResult(res);
      setNextState(res.state);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function askHint() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await assessApi.hint(state.attempt_id);
      setHint(res.hint);
      setHintsUsed(res.hints_used);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  function advance() {
    if (!nextState) return;
    if (nextState.finished) onFinished();
    else onState(nextState);
  }

  return (
    <div className="qcard" ref={topRef}>
      <div className="qcard-head">
        <span className="qstep">
          Question {state.questions_answered + 1} of {state.max_questions}
        </span>
        <span className={`pill pill-${q.difficulty}`}>
          {DIFFICULTY_LABEL[q.difficulty] || q.difficulty}
        </span>
      </div>

      <p className="qtext">{q.question}</p>

      {q.options?.length ? (
        <div role="radiogroup" aria-label="Answer options">
          {q.options.map((opt, i) => {
            let cls = 'opt';
            if (result) {
              if (opt === result.correct_answer || (result.is_correct && opt === choice)) cls += ' right';
              else if (opt === choice) cls += ' wrong';
            } else if (opt === choice) {
              cls += ' chosen';
            }
            return (
              <button
                key={i}
                className={cls}
                onClick={() => !result && setChoice(opt)}
                disabled={!!result || busy}
                role="radio"
                aria-checked={choice === opt}
                type="button"
              >
                <span className="k">{KEY[i]}</span>
                <span className="txt">{opt}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="field">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!!result || busy}
            placeholder="Answer in your own words — you're graded on the concept, not the wording."
            style={{ minHeight: 110 }}
            aria-label="Your answer"
          />
        </div>
      )}

      {hint && !result && (
        <div className="hintbox">
          <b>Hint</b>
          {hint}
        </div>
      )}

      {result && (
        <div className={`feedback${result.is_correct ? '' : ' miss'}`}>
          <div className="feedback-head">
            {result.is_correct ? <Check style={{ width: 15, height: 15 }} /> : <Cross style={{ width: 15, height: 15 }} />}
            {result.is_correct ? 'Correct' : 'Not quite'}
          </div>
          {!result.is_correct && result.correct_answer && (
            <p style={{ marginBottom: 8 }}>
              <strong>Answer:</strong> {result.correct_answer}
            </p>
          )}
          <Markdown>{result.feedback}</Markdown>
        </div>
      )}

      <div className="row gap8" style={{ marginTop: 14, flexWrap: 'wrap' }}>
        {!result ? (
          <>
            <button className="btn btn-marker btn-lg" onClick={submit} disabled={!answerValue || busy} type="button">
              {busy ? 'Checking…' : 'Submit answer'}
            </button>
            <button className="btn btn-ghost" onClick={askHint} disabled={busy} type="button">
              <Bulb style={{ width: 15, height: 15 }} />
              {hintsUsed ? 'Another hint' : 'Hint'}
            </button>
          </>
        ) : (
          <button className="btn btn-ink btn-lg" onClick={advance} type="button">
            {nextState?.finished ? 'See results' : 'Next question'}
          </button>
        )}
      </div>

      {hintsUsed > 0 && !result && (
        <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
          Using hints lowers the mastery you earn on this question.
        </p>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { assessments as assessApi } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import Markdown from '../../components/Markdown';
import { DIFFICULTY_LABEL } from '../../lib/format';
import { Bulb, Check, Cross } from '../../lib/icons';

/**
 * Coding assessment with "teach from the error" (PRD 7.4).
 *
 * A failing submission does NOT consume the question — the student keeps
 * iterating with hints until the tests pass or they explicitly give up.
 */
export default function CodingRunner({ state, onState, onFinished }) {
  const toast = useToast();
  const [code, setCode] = useState('');
  const [run, setRun] = useState(null); // last CodeSubmitResponse
  const [hint, setHint] = useState(null);
  const [hintsUsed, setHintsUsed] = useState(0);
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const resultsRef = useRef(null);

  const q = state.question;

  useEffect(() => {
    setCode(q?.starter_code || 'def solve():\n    pass\n');
    setRun(null);
    setHint(null);
    setHintsUsed(0);
    setAttempts(0);
  }, [q?.id]);

  if (!q) return null;

  const solved = run?.passed;
  const gaveUp = !!run?.solution;
  const resolved = solved || gaveUp;

  async function submit(giveUp = false) {
    if (busy) return;
    setBusy(true);
    setHint(null);
    try {
      const res = await assessApi.submitCode(state.attempt_id, {
        code,
        language: 'python',
        hints_used: hintsUsed,
        give_up: giveUp,
      });
      setRun(res);
      if (!res.passed && !giveUp) setAttempts((a) => a + 1);
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
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
      const res = await assessApi.hint(state.attempt_id, { code });
      setHint(res.hint);
      setHintsUsed(res.hints_used);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  function advance() {
    const next = run?.state;
    if (!next) return;
    if (next.finished) onFinished();
    else onState(next);
  }

  return (
    <>
      {/* ---------------- problem ---------------- */}
      <div className="qcard">
        <div className="qcard-head">
          <span className="qstep">
            Problem {state.questions_answered + 1} of {state.max_questions}
          </span>
          <span className={`pill pill-${q.difficulty}`}>
            {DIFFICULTY_LABEL[q.difficulty] || q.difficulty}
          </span>
          {attempts > 0 && !resolved && (
            <span className="badge">{attempts} attempt{attempts > 1 ? 's' : ''}</span>
          )}
        </div>

        <Markdown>{q.question}</Markdown>

        {q.visible_tests?.length > 0 && (
          <div className="tests" style={{ marginTop: 14 }}>
            <div className="tests-head">Sample cases</div>
            {q.visible_tests.map((t, i) => (
              <div className="test" key={i}>
                <div className="test-body">
                  <div className="test-io">
                    <b>{t.input}</b> → {t.expected}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {hint && !resolved && (
          <div className="hintbox" style={{ marginTop: 14 }}>
            <b>Hint</b>
            {hint}
          </div>
        )}
      </div>

      {/* ---------------- editor + results ---------------- */}
      <div className="stack gap16">
        <div className="editor-wrap">
          <div className="editor-bar">
            <span className="name">solution.py</span>
            <span className="muted grow" style={{ fontSize: 12.5, textAlign: 'right' }}>
              Python 3 · no network · 8s limit
            </span>
          </div>
          <div className="editor-host">
            <Editor
              height="100%"
              defaultLanguage="python"
              theme="vs-dark"
              value={code}
              onChange={(v) => setCode(v ?? '')}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                fontFamily: '"JetBrains Mono", Consolas, monospace',
                scrollBeyondLastLine: false,
                tabSize: 4,
                readOnly: resolved || busy,
                automaticLayout: true,
                padding: { top: 12 },
              }}
              loading={<div className="center-pad"><span className="spinner" /></div>}
            />
          </div>
          <div className="editor-actions">
            {!resolved ? (
              <>
                <button className="btn btn-marker btn-lg" onClick={() => submit(false)} disabled={busy} type="button">
                  {busy ? 'Running…' : 'Run tests'}
                </button>
                <button className="btn btn-ghost" onClick={askHint} disabled={busy} type="button">
                  <Bulb style={{ width: 15, height: 15 }} />
                  {hintsUsed ? 'Another hint' : 'Hint'}
                </button>
                {attempts >= 1 && (
                  <button
                    className="btn btn-ghost"
                    onClick={() => {
                      if (window.confirm('Show the solution? This counts as needing help and lowers your mastery.')) submit(true);
                    }}
                    disabled={busy}
                    type="button"
                  >
                    Show solution
                  </button>
                )}
              </>
            ) : (
              <button className="btn btn-ink btn-lg" onClick={advance} type="button">
                {run.state?.finished ? 'See results' : 'Next problem'}
              </button>
            )}
          </div>
        </div>

        <div ref={resultsRef}>
          {run && (
            <>
              {run.tests?.length > 0 && (
                <div className="tests">
                  <div className="tests-head">
                    {run.passed ? (
                      <span className="badge badge-green"><Check />All tests passed</span>
                    ) : (
                      <span className="badge badge-red">
                        <Cross />
                        {run.tests.filter((t) => t.passed).length} of {run.tests.length} passed
                      </span>
                    )}
                    <span className="muted grow" style={{ textAlign: 'right', fontWeight: 400 }}>
                      {run.runtime_ms}ms
                    </span>
                  </div>
                  {run.tests.map((t, i) => (
                    <div className={`test ${t.passed ? 'pass' : 'fail'}`} key={i}>
                      <span className="test-mark">{t.passed ? <Check /> : <Cross />}</span>
                      <div className="test-body">
                        <div className="test-name">{t.name}</div>
                        <div className="test-io">
                          <b>{t.input}</b> → expected {t.expected}
                          {!t.passed && t.actual != null && <> · got {t.actual}</>}
                        </div>
                        {t.error && <pre className="test-err">{t.error}</pre>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {run.stdout && (
                <div className="tests" style={{ marginTop: 12 }}>
                  <div className="tests-head">Your output</div>
                  <div className="console">{run.stdout}</div>
                </div>
              )}

              {!run.tests?.length && run.stderr && (
                <div className="tests" style={{ marginTop: 12 }}>
                  <div className="tests-head">Error</div>
                  <div className="console">{run.stderr}</div>
                </div>
              )}

              {run.feedback && (
                <div className={`feedback${run.passed ? '' : ' miss'}`} style={{ marginTop: 14 }}>
                  <div className="feedback-head">
                    {run.passed ? <Check style={{ width: 15, height: 15 }} /> : <Cross style={{ width: 15, height: 15 }} />}
                    {run.passed ? 'Code review' : gaveUp ? 'Walkthrough' : 'What went wrong'}
                  </div>
                  <Markdown>{run.feedback}</Markdown>
                </div>
              )}

              {run.hint && !run.passed && !gaveUp && (
                <div className="hintbox" style={{ marginTop: 12 }}>
                  <b>Try this</b>
                  {run.hint}
                </div>
              )}

              {!resolved && (
                <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
                  This doesn&apos;t count against you yet — fix it and run the tests again.
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

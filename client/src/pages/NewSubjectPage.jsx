import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { subjects as subjectsApi } from '../lib/api';
import { useToast } from '../context/ToastContext';
import { useChrome } from '../lib/useChrome';
import TreeEditor, { cleanTree, emptyTopic } from '../components/TreeEditor';
import { Doc, Upload } from '../lib/icons';

const MAX_MB = 15;

export default function NewSubjectPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const fileInput = useRef(null);

  const [mode, setMode] = useState('upload'); // upload | manual
  const [name, setName] = useState('');
  const [type, setType] = useState('non-coding');
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  // populated after a successful upload — the draft awaiting confirmation
  const [draft, setDraft] = useState(null);
  const [topics, setTopics] = useState([emptyTopic()]);

  useChrome(
    <>
      <Link to="/">All subjects</Link>
      <span>/</span>
      <span className="now">New subject</span>
    </>,
    {},
    [],
  );

  function pickFile(f) {
    if (!f) return;
    if (f.size > MAX_MB * 1024 * 1024) {
      toast.error(`That file is over ${MAX_MB}MB. Try a smaller PDF.`);
      return;
    }
    setFile(f);
    if (!name.trim()) {
      setName(f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim());
    }
  }

  async function upload(e) {
    e.preventDefault();
    if (!file) {
      toast.error('Choose a syllabus file first.');
      return;
    }
    setBusy(true);
    try {
      const parsed = await subjectsApi.upload({ file, name: name.trim(), type });
      setDraft(parsed);
      setTopics(parsed.topics?.length ? parsed.topics : [emptyTopic()]);
      if (parsed.needs_manual_entry) toast.show(parsed.message);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirmDraft() {
    const clean = cleanTree(topics);
    if (!clean.length) {
      toast.error('Add at least one topic before confirming.');
      return;
    }
    setBusy(true);
    try {
      await subjectsApi.confirm(draft.subject_id, clean);
      toast.success('Subject is ready. Start studying.');
      navigate(`/subjects/${draft.subject_id}`);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function createManual(e) {
    e.preventDefault();
    const clean = cleanTree(topics);
    if (!name.trim()) {
      toast.error('Give the subject a name.');
      return;
    }
    if (!clean.length) {
      toast.error('Add at least one topic.');
      return;
    }
    setBusy(true);
    try {
      const created = await subjectsApi.create({ name: name.trim(), type, topics: clean });
      toast.success('Subject created.');
      navigate(`/subjects/${created.id}`);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  /* ---------------- draft review step ---------------- */
  if (draft) {
    const confidence = Math.round((draft.confidence || 0) * 100);
    return (
      <>
        <section className="band">
          <div className="wrap">
            <p className="band-meta">Step 2 of 2 · review</p>
            <h1 className="band-title">{name}</h1>
            <p className="band-sub">{draft.message}</p>
          </div>
        </section>

        <section className="wrap section" style={{ maxWidth: 760 }}>
          <div className="confidence">
            <span>Extraction confidence</span>
            <span className="bar">
              <span
                style={{
                  width: `${confidence}%`,
                  background: confidence >= 60 ? 'var(--green)' : confidence >= 35 ? 'var(--gold-deep)' : 'var(--red)',
                }}
              />
            </span>
            <span className="mono">{confidence}%</span>
          </div>

          <p className="muted" style={{ marginBottom: 14 }}>
            Edit anything that looks wrong — auto-extraction is a starting point, not the
            final tree. Nothing is saved until you confirm.
          </p>

          <TreeEditor topics={topics} onChange={setTopics} />

          <div className="modal-actions" style={{ marginTop: 20 }}>
            <button className="btn btn-ghost" onClick={() => setDraft(null)} disabled={busy} type="button">
              Back
            </button>
            <button className="btn btn-marker btn-lg" onClick={confirmDraft} disabled={busy} type="button">
              {busy ? 'Saving…' : 'Confirm tree'}
            </button>
          </div>
        </section>
      </>
    );
  }

  /* ---------------- create step ---------------- */
  return (
    <>
      <section className="band">
        <div className="wrap">
          <p className="band-meta">Step 1 of 2</p>
          <h1 className="band-title">Add a subject</h1>
          <p className="band-sub">
            Upload your syllabus and we&apos;ll parse it into topics and sub-topics for you
            to review — or build the tree by hand.
          </p>
        </div>
      </section>

      <section className="wrap section" style={{ maxWidth: 760 }}>
        <div className="seg" style={{ marginBottom: 20 }}>
          <button type="button" aria-pressed={mode === 'upload'} onClick={() => setMode('upload')}>
            Upload syllabus
          </button>
          <button type="button" aria-pressed={mode === 'manual'} onClick={() => setMode('manual')}>
            Enter manually
          </button>
        </div>

        <form onSubmit={mode === 'upload' ? upload : createManual}>
          <div className="row2">
            <div className="field">
              <label htmlFor="sname">Subject name</label>
              <input
                id="sname"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Database Management Systems"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="stype">Type</label>
              <select id="stype" value={type} onChange={(e) => setType(e.target.value)}>
                <option value="non-coding">Theory</option>
                <option value="coding">Coding</option>
              </select>
              <span className="sub">
                {type === 'coding'
                  ? 'Assessments give you problems to solve in a code editor.'
                  : 'Assessments are questions with an adaptive difficulty ladder.'}
              </span>
            </div>
          </div>

          {mode === 'upload' ? (
            <>
              <div className="field">
                <label htmlFor="syl">Syllabus file</label>
                <div
                  className={`drop${dragging ? ' over' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    pickFile(e.dataTransfer.files?.[0]);
                  }}
                >
                  {file ? (
                    <>
                      <Doc style={{ width: 26, height: 26, margin: '0 auto 8px', color: 'var(--ink)' }} />
                      <strong>{file.name}</strong>
                      <p className="muted" style={{ fontSize: 13 }}>
                        {(file.size / 1024).toFixed(0)} KB · click below to replace
                      </p>
                    </>
                  ) : (
                    <>
                      <Upload style={{ width: 26, height: 26, margin: '0 auto 8px', color: 'var(--muted)' }} />
                      <strong>Drop your syllabus here</strong>
                      <p className="muted" style={{ fontSize: 13 }}>PDF or text, up to {MAX_MB}MB</p>
                    </>
                  )}
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ marginTop: 12 }}
                    type="button"
                    onClick={() => fileInput.current?.click()}
                  >
                    {file ? 'Choose a different file' : 'Choose file'}
                  </button>
                  <input
                    id="syl"
                    ref={fileInput}
                    type="file"
                    accept=".pdf,.txt,.md,text/plain,application/pdf"
                    hidden
                    onChange={(e) => pickFile(e.target.files?.[0])}
                  />
                </div>
                <span className="sub">
                  Scanned or image-only PDFs can&apos;t be read — you&apos;ll be asked to enter
                  topics manually if that happens.
                </span>
              </div>

              <button className="btn btn-marker btn-lg" disabled={busy || !file} type="submit">
                {busy ? 'Reading your syllabus…' : 'Parse syllabus'}
              </button>
            </>
          ) : (
            <>
              <div className="field">
                <label>Topics and sub-topics</label>
                <span className="sub">
                  Two levels: a topic (like a unit) and the sub-topics inside it. You study
                  and get tested one sub-topic at a time.
                </span>
              </div>

              <TreeEditor topics={topics} onChange={setTopics} />

              <button className="btn btn-marker btn-lg" style={{ marginTop: 20 }} disabled={busy} type="submit">
                {busy ? 'Creating…' : 'Create subject'}
              </button>
            </>
          )}
        </form>
      </section>
    </>
  );
}

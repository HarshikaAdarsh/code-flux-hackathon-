import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { assessments as assessApi, fileUrl, subjects as subjectsApi } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useChrome } from '../lib/useChrome';
import { spineColor } from '../lib/format';
import TopicTree from '../features/tree/TopicTree';
import TutorPanel from '../features/tutor/TutorPanel';
import TreeEditor, { cleanTree, emptyTopic } from '../components/TreeEditor';
import Modal from '../components/Modal';
import { Chart, Doc, Pencil, Trash } from '../lib/icons';

export default function SubjectPage() {
  const { id } = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { language } = useAuth();

  const [tree, setTree] = useState(null);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [starting, setStarting] = useState(false);
  const [draftTopics, setDraftTopics] = useState([emptyTopic()]);
  const [confirming, setConfirming] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [form, setForm] = useState({ name: '', type: 'non-coding' });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const data = await subjectsApi.tree(id);
    setTree(data);
    return data;
  }, [id]);

  useEffect(() => {
    let alive = true;
    setTree(null);
    setError('');
    setSelectedId(null);
    load()
      .then((data) => {
        if (!alive) return;
        // A draft subject has no committed tree yet (PRD 7.1 / open question 4).
        if (data.status === 'draft') setDraftTopics(data.topics?.length ? data.topics : [emptyTopic()]);
        // ?subtopic= wins (history "Continue" links here); otherwise pick the
        // first unfinished sub-topic so the tutor always has a scope.
        const all = data.topics.flatMap((t) => t.subtopics);
        const requested = search.get('subtopic');
        const target =
          (requested && all.find((s) => s.id === requested)) ||
          all.find((s) => !s.is_completed) ||
          all[0];
        if (target) setSelectedId(target.id);
      })
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [load]);

  const { topic, subtopic } = useMemo(() => {
    if (!tree || !selectedId) return { topic: null, subtopic: null };
    for (const t of tree.topics) {
      const s = t.subtopics.find((x) => x.id === selectedId);
      if (s) return { topic: t, subtopic: s };
    }
    return { topic: null, subtopic: null };
  }, [tree, selectedId]);

  useChrome(
    <>
      <Link to="/">All subjects</Link>
      <span>/</span>
      <span className="now">{tree?.name || '…'}</span>
    </>,
    { subjectId: id, subtopicId: selectedId },
    [tree?.name, id, selectedId],
  );

  const startAssessment = useCallback(
    async (target) => {
      const s = target || subtopic;
      if (!s) return;
      if (!s.is_completed) {
        toast.error('Tick this sub-topic as done first — assessments only cover what you have studied.');
        return;
      }
      setStarting(true);
      try {
        const state = await assessApi.start({ subtopic_id: s.id, language });
        navigate(`/assessments/${state.attempt_id}`, {
          state: { subjectId: id, subtopicId: s.id, subtopicTitle: s.title },
        });
      } catch (err) {
        toast.error(err);
      } finally {
        setStarting(false);
      }
    },
    [subtopic, language, navigate, id, toast],
  );

  async function confirmDraft() {
    const clean = cleanTree(draftTopics);
    if (!clean.length) {
      toast.error('Add at least one topic before confirming.');
      return;
    }
    setConfirming(true);
    try {
      await subjectsApi.confirm(id, clean);
      toast.success('Tree confirmed. Time to study.');
      await load();
    } catch (err) {
      toast.error(err);
    } finally {
      setConfirming(false);
    }
  }

  function openSettings() {
    setForm({ name: tree.name, type: tree.type });
    setSettingsOpen(true);
  }

  async function saveSettings() {
    if (!form.name.trim()) {
      toast.error('The subject needs a name.');
      return;
    }
    setSaving(true);
    try {
      await subjectsApi.update(id, { name: form.name.trim(), type: form.type });
      await load();
      setSettingsOpen(false);
      toast.success('Subject updated.');
    } catch (err) {
      toast.error(err);
    } finally {
      setSaving(false);
    }
  }

  async function removeSubject() {
    if (!window.confirm(`Delete “${tree.name}”? Its chats, tests and progress are deleted too.`)) return;
    try {
      await subjectsApi.remove(id);
      toast.success('Subject deleted.');
      navigate('/');
    } catch (err) {
      toast.error(err);
    }
  }

  if (error) {
    return (
      <div className="center-pad">
        <h2>Couldn&apos;t load this subject</h2>
        <p className="muted">{error}</p>
        <Link className="btn btn-ghost" to="/">Back to subjects</Link>
      </div>
    );
  }

  if (!tree) {
    return (
      <div className="center-pad">
        <span className="spinner lg" />
        <p className="muted">Loading syllabus…</p>
      </div>
    );
  }

  const spine = spineColor(tree.id);
  const p = tree.progress || {};

  /* -------- draft: the parsed tree still needs confirming -------- */
  if (tree.status === 'draft') {
    return (
      <>
        <section className="band" style={{ backgroundColor: spine }}>
          <div className="wrap">
            <p className="band-meta">Draft · needs your review</p>
            <h1 className="band-title">{tree.name}</h1>
            <p className="band-sub">
              We parsed this syllabus but nothing is saved to your tree yet. Edit anything
              that looks wrong, then confirm.
            </p>
          </div>
        </section>

        <section className="wrap section" style={{ maxWidth: 760 }}>
          <TreeEditor topics={draftTopics} onChange={setDraftTopics} />
          <div className="modal-actions" style={{ marginTop: 20 }}>
            <button className="btn btn-danger" onClick={removeSubject} type="button">
              Discard subject
            </button>
            <button className="btn btn-marker btn-lg" onClick={confirmDraft} disabled={confirming} type="button">
              {confirming ? 'Saving…' : 'Confirm tree'}
            </button>
          </div>
        </section>
      </>
    );
  }

  /* -------- active workspace -------- */
  return (
    <>
      <section className="band" style={{ backgroundColor: spine }}>
        <div className="wrap">
          <p className="band-meta">
            <span className="pill">{tree.type === 'coding' ? 'Coding' : 'Theory'}</span>
            <span>{tree.topics.length} topics · {p.total_subtopics} sub-topics</span>
          </p>
          <h1 className="band-title">{tree.name}</h1>
          <div className="band-progress">
            <span className="bar thick">
              <span style={{ width: `${p.percent_complete || 0}%` }} />
            </span>
            <span>{p.completed_subtopics} of {p.total_subtopics} done · avg mastery {p.avg_mastery}</span>
          </div>
          <div className="band-actions">
            <Link className="btn btn-marker" to={`/subjects/${id}/report`}>
              <Chart style={{ width: 15, height: 15 }} />
              Strengths &amp; weaknesses
            </Link>
            <Link className="btn btn-ghost" to={`/subjects/${id}/history`}>
              <Doc style={{ width: 15, height: 15 }} />
              History
            </Link>
            <button className="btn btn-ghost" onClick={openSettings} type="button">
              <Pencil style={{ width: 15, height: 15 }} />
              Settings
            </button>
          </div>
        </div>
      </section>

      <div className="wrap workspace">
        <TopicTree
          tree={tree}
          selectedId={selectedId}
          onSelect={(s) => setSelectedId(s.id)}
          onChanged={load}
          onAssess={startAssessment}
        />
        <TutorPanel
          subject={tree}
          topic={topic}
          subtopic={subtopic}
          language={language}
          onAssess={startAssessment}
        />
      </div>

      <Modal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="Subject settings"
        hint="Changing the type switches how assessments work: coding subjects give you problems to solve in an editor."
        actions={(
          <>
            <button className="btn btn-danger" onClick={removeSubject} type="button">
              <Trash style={{ width: 14, height: 14 }} />
              Delete subject
            </button>
            <button className="btn btn-ghost" onClick={() => setSettingsOpen(false)} type="button">
              Cancel
            </button>
            <button className="btn btn-marker" onClick={saveSettings} disabled={saving} type="button">
              {saving ? 'Saving…' : 'Save'}
            </button>
          </>
        )}
      >
        <div className="field">
          <label htmlFor="sname">Name</label>
          <input
            id="sname"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="stype">Type</label>
          <select
            id="stype"
            value={form.type}
            onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
          >
            <option value="non-coding">Theory</option>
            <option value="coding">Coding</option>
          </select>
        </div>
        {tree.syllabus_file_url && (
          <p className="muted" style={{ fontSize: 13 }}>
            Uploaded syllabus:{' '}
            <a href={fileUrl(tree.syllabus_file_url)} target="_blank" rel="noreferrer">
              open the original file
            </a>
          </p>
        )}
      </Modal>

      {starting && (
        <div className="backdrop">
          <div className="modal" style={{ textAlign: 'center' }}>
            <span className="spinner lg" style={{ margin: '0 auto 14px' }} />
            <h2>Preparing your questions</h2>
            <p className="hint" style={{ marginBottom: 0 }}>
              The first assessment on a sub-topic generates its question pool. After that
              it&apos;s instant.
            </p>
          </div>
        </div>
      )}
    </>
  );
}

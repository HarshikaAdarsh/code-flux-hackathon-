import { useState } from 'react';
import { subjects as subjectsApi, subtopics as subtopicApi, topics as topicApi } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import { masteryColor } from '../../lib/format';
import { Brain, Caret, Check, Plus, Trash } from '../../lib/icons';

function Checkbox({ checked, onToggle, busy, label }) {
  return (
    <button
      className={`check${busy ? ' busy' : ''}`}
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      type="button"
    >
      <Check />
    </button>
  );
}

function Mastery({ score }) {
  return (
    <span className="mastery" title={`Mastery ${score}/100 (decays over time)`}>
      <span className="bar">
        <span style={{ width: `${score}%`, background: masteryColor(score) }} />
      </span>
      {score}
    </span>
  );
}

export default function TopicTree({ tree, selectedId, onSelect, onChanged, onAssess }) {
  const toast = useToast();
  const [collapsed, setCollapsed] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [editing, setEditing] = useState(null); // {kind, id, value}
  const [adding, setAdding] = useState(null); // topicId | 'topic'
  const [draft, setDraft] = useState('');

  const run = async (id, fn) => {
    setBusyId(id);
    try {
      await fn();
      await onChanged();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusyId(null);
    }
  };

  const toggleSubtopic = (s) =>
    run(s.id, () => subtopicApi.patch(s.id, { is_completed: !s.is_completed }));

  const toggleTopic = (t) =>
    run(t.id, () => topicApi.patch(t.id, { is_completed: !t.is_completed }));

  const saveEdit = async () => {
    const value = editing.value.trim();
    if (!value) {
      setEditing(null);
      return;
    }
    const { kind, id } = editing;
    setEditing(null);
    await run(id, () =>
      kind === 'topic'
        ? topicApi.patch(id, { title: value })
        : subtopicApi.patch(id, { title: value }),
    );
  };

  const commitAdd = async () => {
    const value = draft.trim();
    const target = adding;
    setAdding(null);
    setDraft('');
    if (!value) return;
    await run(target, () =>
      target === 'topic'
        ? subjectsApi.addTopic(tree.id, { title: value, subtopics: [] })
        : topicApi.addSubtopic(target, value),
    );
  };

  const removeTopic = (t) => {
    if (!window.confirm(`Delete “${t.title}” and its ${t.subtopics.length} sub-topics? Progress on them is lost.`)) return;
    run(t.id, () => topicApi.remove(t.id));
  };

  const removeSubtopic = (s) => {
    if (!window.confirm(`Delete “${s.title}”? Its chats and test history go too.`)) return;
    run(s.id, () => subtopicApi.remove(s.id));
  };

  const editorInput = (onCommit, onCancel, value, setValue, placeholder) => (
    <input
      className="grow"
      autoFocus
      value={value}
      placeholder={placeholder}
      onChange={(e) => setValue(e.target.value)}
      onBlur={onCommit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onCommit();
        if (e.key === 'Escape') onCancel();
      }}
      style={{
        font: 'inherit',
        fontSize: 14.5,
        padding: '5px 8px',
        borderRadius: 7,
        border: '1.5px solid var(--ink)',
        background: '#fff',
        minWidth: 0,
      }}
    />
  );

  return (
    <section className="syllabus">
      <div className="syllabus-head">
        <h2>Syllabus</h2>
        <span className="muted">
          {tree.progress?.completed_subtopics ?? 0} of {tree.progress?.total_subtopics ?? 0} done
        </span>
      </div>

      {tree.topics.length === 0 && (
        <div className="empty">
          <h3>This tree is empty</h3>
          <p>Add your first topic to start studying.</p>
        </div>
      )}

      {tree.topics.map((t) => {
        const isOpen = !collapsed[t.id];
        return (
          <div className="unit" key={t.id}>
            <div className="unit-head">
              <button
                className="tool"
                onClick={() => setCollapsed((c) => ({ ...c, [t.id]: isOpen }))}
                aria-label={isOpen ? `Collapse ${t.title}` : `Expand ${t.title}`}
                aria-expanded={isOpen}
                type="button"
              >
                <Caret className={`unit-caret${isOpen ? ' open' : ''}`} />
              </button>

              <Checkbox
                checked={t.is_completed}
                busy={busyId === t.id}
                onToggle={() => toggleTopic(t)}
                label={`Mark topic ${t.title} ${t.is_completed ? 'incomplete' : 'complete'}`}
              />

              {editing?.kind === 'topic' && editing.id === t.id ? (
                editorInput(
                  saveEdit,
                  () => setEditing(null),
                  editing.value,
                  (v) => setEditing((e) => ({ ...e, value: v })),
                  'Topic name',
                )
              ) : (
                <button
                  className="unit-title"
                  onDoubleClick={() => setEditing({ kind: 'topic', id: t.id, value: t.title })}
                  title="Double-click to rename"
                  type="button"
                >
                  {t.title}
                </button>
              )}

              <span className="unit-tools">
                <button className="tool" onClick={() => { setAdding(t.id); setDraft(''); }} title="Add sub-topic" aria-label={`Add sub-topic to ${t.title}`} type="button">
                  <Plus />
                </button>
                <button className="tool danger" onClick={() => removeTopic(t)} title="Delete topic" aria-label={`Delete topic ${t.title}`} type="button">
                  <Trash />
                </button>
              </span>
            </div>

            {isOpen && (
              <ul>
                {t.subtopics.map((s) => {
                  const selected = s.id === selectedId;
                  return (
                    <li key={s.id}>
                      <div className="topic-row">
                        <Checkbox
                          checked={s.is_completed}
                          busy={busyId === s.id}
                          onToggle={() => toggleSubtopic(s)}
                          label={`Mark ${s.title} ${s.is_completed ? 'incomplete' : 'complete'}`}
                        />

                        {editing?.kind === 'sub' && editing.id === s.id ? (
                          <div style={{ flex: 1, padding: '4px 0' }}>
                            {editorInput(
                              saveEdit,
                              () => setEditing(null),
                              editing.value,
                              (v) => setEditing((e) => ({ ...e, value: v })),
                              'Sub-topic name',
                            )}
                          </div>
                        ) : (
                          <button
                            className={`topic${selected ? ' selected' : ''}${s.is_completed ? ' done' : ''}`}
                            onClick={() => onSelect(s, t)}
                            onDoubleClick={() => setEditing({ kind: 'sub', id: s.id, value: s.title })}
                            type="button"
                          >
                            <span className="topic-name">{s.title}</span>
                            <Mastery score={s.mastery_score} />
                          </button>
                        )}

                        <span className="tools">
                          {s.is_completed && (
                            <button
                              className="tool"
                              onClick={() => onAssess(s)}
                              title="Test yourself on this sub-topic"
                              aria-label={`Start assessment on ${s.title}`}
                              type="button"
                            >
                              <Brain />
                            </button>
                          )}
                          <button className="tool danger" onClick={() => removeSubtopic(s)} title="Delete sub-topic" aria-label={`Delete ${s.title}`} type="button">
                            <Trash />
                          </button>
                        </span>
                      </div>
                    </li>
                  );
                })}

                {adding === t.id && (
                  <li>
                    <div className="rt-sub" style={{ paddingLeft: 34, paddingRight: 8 }}>
                      {editorInput(commitAdd, () => { setAdding(null); setDraft(''); }, draft, setDraft, 'New sub-topic')}
                    </div>
                  </li>
                )}
              </ul>
            )}
          </div>
        );
      })}

      <div style={{ padding: '10px 22px 4px' }}>
        {adding === 'topic' ? (
          editorInput(commitAdd, () => { setAdding(null); setDraft(''); }, draft, setDraft, 'New topic')
        ) : (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => { setAdding('topic'); setDraft(''); }}
            type="button"
          >
            <Plus style={{ width: 14, height: 14 }} />
            Add topic
          </button>
        )}
      </div>
    </section>
  );
}

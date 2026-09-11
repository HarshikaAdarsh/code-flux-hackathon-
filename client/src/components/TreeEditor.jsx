import { Plus, Trash } from '../lib/icons';

/**
 * Editable two-level tree: topic -> sub-topics.
 * The backend enforces the same shape (PRD open question 5: 50 topics max,
 * 12 sub-topics per topic, exactly two levels).
 */
export const MAX_TOPICS = 50;
export const MAX_SUBTOPICS = 12;

export const emptyTopic = () => ({ title: '', subtopics: [{ title: '' }] });

/** Strip blank rows before sending to the API. */
export function cleanTree(topics) {
  return topics
    .map((t) => ({
      title: t.title.trim(),
      subtopics: (t.subtopics || []).map((s) => ({ title: s.title.trim() })).filter((s) => s.title),
    }))
    .filter((t) => t.title)
    .map((t) => ({
      ...t,
      // the API requires at least one sub-topic; mirror its fallback
      subtopics: t.subtopics.length ? t.subtopics : [{ title: t.title }],
    }));
}

export default function TreeEditor({ topics, onChange }) {
  const update = (next) => onChange(next);

  const setTopicTitle = (ti, title) =>
    update(topics.map((t, i) => (i === ti ? { ...t, title } : t)));

  const setSubTitle = (ti, si, title) =>
    update(
      topics.map((t, i) =>
        i === ti
          ? { ...t, subtopics: t.subtopics.map((s, j) => (j === si ? { title } : s)) }
          : t,
      ),
    );

  const addTopic = () => update([...topics, emptyTopic()]);
  const removeTopic = (ti) => update(topics.filter((_, i) => i !== ti));

  const addSub = (ti) =>
    update(
      topics.map((t, i) =>
        i === ti && t.subtopics.length < MAX_SUBTOPICS
          ? { ...t, subtopics: [...t.subtopics, { title: '' }] }
          : t,
      ),
    );

  const removeSub = (ti, si) =>
    update(
      topics.map((t, i) =>
        i === ti ? { ...t, subtopics: t.subtopics.filter((_, j) => j !== si) } : t,
      ),
    );

  return (
    <>
      <div className="review-tree">
        {topics.length === 0 && (
          <p className="muted" style={{ padding: 16, textAlign: 'center' }}>
            No topics yet. Add your first one below.
          </p>
        )}

        {topics.map((t, ti) => (
          <div className="rt-unit" key={ti}>
            <div className="rt-unit-head">
              <input
                value={t.title}
                onChange={(e) => setTopicTitle(ti, e.target.value)}
                placeholder={`Topic ${ti + 1} — e.g. "Normalization"`}
                aria-label={`Topic ${ti + 1} title`}
              />
              <button
                className="tool danger"
                onClick={() => removeTopic(ti)}
                title="Remove this topic"
                aria-label={`Remove topic ${t.title || ti + 1}`}
                type="button"
              >
                <Trash />
              </button>
            </div>

            {t.subtopics.map((s, si) => (
              <div className="rt-sub" key={si}>
                <input
                  value={s.title}
                  onChange={(e) => setSubTitle(ti, si, e.target.value)}
                  placeholder="Sub-topic"
                  aria-label={`Sub-topic ${si + 1} of ${t.title || `topic ${ti + 1}`}`}
                />
                <button
                  className="tool danger"
                  onClick={() => removeSub(ti, si)}
                  title="Remove this sub-topic"
                  aria-label={`Remove sub-topic ${s.title || si + 1}`}
                  type="button"
                >
                  <Trash />
                </button>
              </div>
            ))}

            {t.subtopics.length < MAX_SUBTOPICS && (
              <button className="rt-add" onClick={() => addSub(ti)} type="button">
                + Add sub-topic
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="row gap12" style={{ marginTop: 12, flexWrap: 'wrap' }}>
        <button
          className="btn btn-ghost btn-sm"
          onClick={addTopic}
          disabled={topics.length >= MAX_TOPICS}
          type="button"
        >
          <Plus style={{ width: 14, height: 14 }} />
          Add topic
        </button>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {topics.length} of {MAX_TOPICS} topics
          {topics.length >= MAX_TOPICS && ' — merge finer items into sub-topics'}
        </span>
      </div>
    </>
  );
}

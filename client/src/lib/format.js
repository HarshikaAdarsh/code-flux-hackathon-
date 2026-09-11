/* Small presentation helpers shared across pages. */

/** Stable per-subject accent colour, so a subject keeps its spine colour. */
const SPINES = ['#22409A', '#1E7F63', '#B23A48', '#6B3FA0', '#0F7A8A', '#DE7F16'];
export function spineColor(id = '') {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return SPINES[h % SPINES.length];
}

/** Mastery 0-100 -> a traffic-light colour for meters. */
export function masteryColor(score) {
  if (score >= 70) return 'var(--green)';
  if (score >= 40) return 'var(--gold-deep)';
  if (score > 0) return 'var(--red)';
  return 'var(--line-strong)';
}

export const CLASSIFICATION_LABEL = {
  strength: 'Strength',
  weakness: 'Weakness',
  needs_practice: 'Needs practice',
  untested: 'Not tested yet',
};

export const DIFFICULTY_LABEL = { basic: 'Basic', medium: 'Medium', hard: 'Hard' };

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिंदी' },
];

export function initials(name = '') {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0] || '')
      .join('')
      .toUpperCase() || '?'
  );
}

export function clock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export function pct(part, whole) {
  return whole ? Math.round((part / whole) * 100) : 0;
}

export function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export function today() {
  return new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** Count sub-topics in a tree payload. */
export function treeStats(topics = []) {
  let total = 0;
  let done = 0;
  for (const t of topics) {
    for (const s of t.subtopics || []) {
      total += 1;
      if (s.is_completed) done += 1;
    }
  }
  return { total, done, percent: pct(done, total) };
}

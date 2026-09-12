/**
 * Typed-ish wrapper around the study-companion backend.
 * Every call in here maps to an endpoint in the PRD's API surface (section 9).
 */

export const API_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://127.0.0.1:8000';

const TOKEN_KEY = 'sc.token';

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};
export const setToken = (t) => {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode — session-only auth is fine */
  }
};

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** Turn FastAPI's error shapes into one readable sentence. */
function readDetail(body, status) {
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    const first = d[0];
    if (first?.msg) {
      const field = (first.loc || []).filter((x) => x !== 'body').join('.');
      return field ? `${field}: ${first.msg}` : first.msg;
    }
  }
  if (typeof body?.message === 'string') return body.message;
  return `Request failed (${status})`;
}

async function request(path, { method = 'GET', body, form, signal } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (form) {
    payload = form; // browser sets the multipart boundary
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload, signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(
      `Can't reach the server at ${API_URL}. Is the backend running?`,
      0,
      null,
    );
  }

  if (res.status === 204) return null;

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!res.ok) {
    if (res.status === 401) setToken(null);
    throw new ApiError(readDetail(data, res.status), res.status, data);
  }
  return data;
}

export const fileUrl = (p) => (p?.startsWith('/') ? `${API_URL}${p}` : p);

/* ------------------------------------------------------------------ auth */
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

export const auth = {
  signup: (payload) => request('/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload }),
  // Exchanges a Google ID token for our own JWT (PRD 7.7).
  google: (idToken) => request('/auth/google', { method: 'POST', body: { id_token: idToken } }),
  me: () => request('/auth/me'),
  updateMe: (payload) => request('/auth/me', { method: 'PATCH', body: payload }),
};

/* -------------------------------------------------------------- subjects */
export const subjects = {
  list: () => request('/subjects'),
  create: (payload) => request('/subjects', { method: 'POST', body: payload }),
  upload: ({ file, name, type }) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', name);
    fd.append('type', type);
    return request('/subjects/upload', { method: 'POST', form: fd });
  },
  confirm: (id, topics) =>
    request(`/subjects/${id}/confirm`, { method: 'POST', body: { topics } }),
  tree: (id) => request(`/subjects/${id}/tree`),
  replaceTree: (id, topics) =>
    request(`/subjects/${id}/tree`, { method: 'PUT', body: { topics } }),
  update: (id, payload) => request(`/subjects/${id}`, { method: 'PATCH', body: payload }),
  remove: (id) => request(`/subjects/${id}`, { method: 'DELETE' }),
  addTopic: (id, payload) =>
    request(`/subjects/${id}/topics`, { method: 'POST', body: payload }),
};

/* ---------------------------------------------------------------- topics */
export const topics = {
  patch: (id, payload) => request(`/topics/${id}`, { method: 'PATCH', body: payload }),
  remove: (id) => request(`/topics/${id}`, { method: 'DELETE' }),
  addSubtopic: (id, title) =>
    request(`/topics/${id}/subtopics`, { method: 'POST', body: { title } }),
};

export const subtopics = {
  patch: (id, payload) => request(`/subtopics/${id}`, { method: 'PATCH', body: payload }),
  remove: (id) => request(`/subtopics/${id}`, { method: 'DELETE' }),
};

/* -------------------------------------------------------------- teaching */
export const teach = {
  send: (payload) => request('/teach', { method: 'POST', body: payload }),
  sessions: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null),
    ).toString();
    return request(`/teach/sessions${q ? `?${q}` : ''}`);
  },
  session: (id) => request(`/teach/sessions/${id}`),
  removeSession: (id) => request(`/teach/sessions/${id}`, { method: 'DELETE' }),

  /**
   * SSE lesson stream. Calls onEvent for every {type,...} the server sends:
   * session | provider | token | done | error.
   * Returns an abort function.
   */
  stream(payload, { onEvent, onError, signal } = {}) {
    const controller = new AbortController();
    if (signal) signal.addEventListener('abort', () => controller.abort());

    (async () => {
      try {
        const res = await fetch(`${API_URL}/teach/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${getToken()}`,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const text = await res.text().catch(() => '');
          let detail = `Stream failed (${res.status})`;
          try {
            detail = readDetail(JSON.parse(text), res.status);
          } catch {
            /* keep the generic message */
          }
          throw new ApiError(detail, res.status, null);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line
          let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            for (const line of frame.split('\n')) {
              if (!line.startsWith('data:')) continue;
              const raw = line.slice(5).trim();
              if (!raw) continue;
              try {
                onEvent?.(JSON.parse(raw));
              } catch {
                /* ignore a partial frame */
              }
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') onError?.(err);
      }
    })();

    return () => controller.abort();
  },
};

/* ----------------------------------------------------------- assessments */
export const assessments = {
  start: (payload) => request('/assessments/start', { method: 'POST', body: payload }),
  get: (id) => request(`/assessments/${id}`),
  answer: (id, payload) =>
    request(`/assessments/${id}/answer`, { method: 'POST', body: payload }),
  submitCode: (id, payload) =>
    request(`/assessments/${id}/submit-code`, { method: 'POST', body: payload }),
  hint: (id, payload = {}) =>
    request(`/assessments/${id}/hint`, { method: 'POST', body: payload }),
  finish: (id) => request(`/assessments/${id}/finish`, { method: 'POST' }),
  summary: (id) => request(`/assessments/${id}/summary`),
  list: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null),
    ).toString();
    return request(`/assessments${q ? `?${q}` : ''}`);
  },
};

/* --------------------------------------------------------------- reports */
export const reports = {
  subject: (id, aiSummary = true) =>
    request(`/reports/${id}?ai_summary=${aiSummary}`),
};

/* ----------------------------------------------------------------- voice */
export const voice = {
  transcribe: ({ blob, language, filename = 'speech.webm' }) => {
    const fd = new FormData();
    fd.append('file', blob, filename);
    if (language) fd.append('language', language);
    return request('/voice/transcribe', { method: 'POST', form: fd });
  },
  speak: (payload) => request('/voice/speak', { method: 'POST', body: payload }),
  chat: ({ blob, filename = 'speech.webm', subjectId, subtopicId, sessionId, language, speakReply = true }) => {
    const fd = new FormData();
    fd.append('file', blob, filename);
    if (subjectId) fd.append('subject_id', subjectId);
    if (subtopicId) fd.append('subtopic_id', subtopicId);
    if (sessionId) fd.append('session_id', sessionId);
    if (language) fd.append('language', language);
    fd.append('speak_reply', String(speakReply));
    return request('/voice/chat', { method: 'POST', form: fd });
  },
  languages: () => request('/voice/languages'),
};

/* -------------------------------------------------------------- pomodoro */
export const pomodoro = {
  start: (payload) => request('/pomodoro/start', { method: 'POST', body: payload }),
  pause: (id) => request(`/pomodoro/${id}/pause`, { method: 'POST' }),
  resume: (id) => request(`/pomodoro/${id}/resume`, { method: 'POST' }),
  stop: (id, { completed = true, durationMinutes } = {}) => {
    const q = new URLSearchParams({ completed: String(completed) });
    if (durationMinutes != null) q.set('duration_minutes', String(durationMinutes));
    return request(`/pomodoro/${id}/stop?${q}`, { method: 'POST' });
  },
  active: () => request('/pomodoro/active'),
  sessions: (limit = 50) => request(`/pomodoro/sessions?limit=${limit}`),
  stats: (days = 30) => request(`/pomodoro/stats?days=${days}`),
};

/* ---------------------------------------------------------------- health */
export const health = {
  full: () => request('/health/full'),
};

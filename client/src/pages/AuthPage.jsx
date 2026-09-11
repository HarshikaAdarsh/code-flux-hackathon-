import { useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LANGUAGES } from '../lib/format';
import { CubeBook, CubeChat, CubeCheck } from '../lib/icons';

export default function AuthPage() {
  const { user, ready, login, signup } = useAuth();
  const location = useLocation();
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '', preferred_language: 'en' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (ready && user) return <Navigate to={location.state?.from || '/'} replace />;

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'login') {
        await login(form.email.trim(), form.password);
      } else {
        await signup({
          name: form.name.trim(),
          email: form.email.trim(),
          password: form.password,
          preferred_language: form.preferred_language,
        });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="band hero">
        <div className="wrap">
          <div className="hero-blocks" aria-hidden="true">
            <div className="cube cube-a"><CubeBook /></div>
            <div className="cube cube-b"><CubeChat /></div>
            <div className="cube cube-c"><CubeCheck /></div>
            <span className="hexdot hexdot-a" />
            <span className="hexdot hexdot-b" />
          </div>
          <p className="hero-kicker">AI-based smart study companion</p>
          <h1 className="hero-title">Padhlo</h1>
          <p className="hero-sub">
            Turn a syllabus PDF into a study tree, learn each sub-topic with a tutor that
            actually teaches, then test yourself with questions that adapt to your answers.
          </p>
        </div>
      </section>

      <section className="wrap section" style={{ maxWidth: 520 }}>
        <div className="card card-hard">
          <div className="seg" style={{ marginBottom: 18 }}>
            <button type="button" aria-pressed={mode === 'login'} onClick={() => { setMode('login'); setError(''); }}>
              Log in
            </button>
            <button type="button" aria-pressed={mode === 'signup'} onClick={() => { setMode('signup'); setError(''); }}>
              Sign up
            </button>
          </div>

          <form onSubmit={submit}>
            {mode === 'signup' && (
              <div className="field">
                <label htmlFor="name">Your name</label>
                <input id="name" value={form.name} onChange={set('name')} required autoComplete="name" placeholder="Rahul Sharma" />
              </div>
            )}

            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" value={form.email} onChange={set('email')} required autoComplete="email" placeholder="you@college.edu" />
            </div>

            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={set('password')}
                required
                minLength={mode === 'signup' ? 8 : undefined}
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                placeholder={mode === 'signup' ? 'At least 8 characters' : ''}
              />
              {mode === 'signup' && <span className="sub">At least 8 characters.</span>}
            </div>

            {mode === 'signup' && (
              <div className="field">
                <label htmlFor="lang">Teach me in</label>
                <select id="lang" value={form.preferred_language} onChange={set('preferred_language')}>
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>{l.label}</option>
                  ))}
                </select>
                <span className="sub">You can change this any time. Voice works in both.</span>
              </div>
            )}

            {error && <p className="err" style={{ marginBottom: 12 }}>{error}</p>}

            <button className="btn btn-marker btn-lg btn-block" disabled={busy} type="submit">
              {busy ? 'Working…' : mode === 'login' ? 'Log in' : 'Create account'}
            </button>
          </form>
        </div>
      </section>
    </>
  );
}

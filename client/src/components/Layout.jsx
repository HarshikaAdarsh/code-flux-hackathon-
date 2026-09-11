import { useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { initials, LANGUAGES } from '../lib/format';
import { Logout } from '../lib/icons';
import PomodoroWidget from '../features/pomodoro/PomodoroWidget';

function AccountMenu() {
  const { user, logout, updateProfile } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  async function save(patch) {
    setSaving(true);
    try {
      await updateProfile(patch);
    } catch (err) {
      toast.error(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="menu" ref={ref}>
      <button
        className="avatar"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Account settings"
      >
        {initials(user?.name)}
      </button>

      {open && (
        <div className="menu-panel">
          <h4>{user?.name}</h4>
          <p className="muted" style={{ fontSize: 12.5, wordBreak: 'break-all' }}>{user?.email}</p>

          <div className="menu-row">
            <label htmlFor="lang">Language</label>
            <select
              id="lang"
              value={user?.preferred_language || 'en'}
              disabled={saving}
              onChange={(e) => save({ preferred_language: e.target.value })}
              style={{ width: 110, padding: '6px 8px', borderRadius: 8, border: '1.5px solid var(--line-strong)', background: 'var(--paper)', font: 'inherit', fontSize: 13 }}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>

          <div className="menu-row">
            <label htmlFor="pomo">Focus length</label>
            <select
              id="pomo"
              value={user?.pomodoro_minutes || 25}
              disabled={saving}
              onChange={(e) => save({ pomodoro_minutes: Number(e.target.value) })}
              style={{ width: 110, padding: '6px 8px', borderRadius: 8, border: '1.5px solid var(--line-strong)', background: 'var(--paper)', font: 'inherit', fontSize: 13 }}
            >
              {[15, 25, 30, 45, 60].map((m) => (
                <option key={m} value={m}>{m} min</option>
              ))}
            </select>
          </div>

          <button className="btn btn-ghost btn-sm btn-block" style={{ marginTop: 14 }} onClick={logout}>
            <Logout style={{ width: 14, height: 14 }} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const location = useLocation();
  // Pages publish their breadcrumb and focus-session scope up to the chrome.
  const [crumb, setCrumb] = useState(null);
  const [scope, setScope] = useState({});

  // Scroll to top on navigation, but not when only the query string changes.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  // Reset chrome when leaving a page so a stale crumb never lingers.
  useEffect(() => {
    setCrumb(null);
    setScope({});
  }, [location.pathname]);

  return (
    <>
      <header className="topbar">
        <div className="wrap">
          <Link to="/" className="brand" style={{ textDecoration: 'none', color: 'inherit' }}>
            Padhlo
          </Link>
          <span className="brand-tag">syllabus se, topic by topic</span>
          {crumb && <nav className="crumb">{crumb}</nav>}
          <div className="topbar-right">
            <PomodoroWidget subjectId={scope.subjectId} subtopicId={scope.subtopicId} />
            <AccountMenu />
          </div>
        </div>
      </header>

      <main>
        <Outlet context={{ setCrumb, setScope }} />
      </main>

      <footer className="site-footer">
        <div className="wrap">
          <span className="footer-brand">Padhlo</span>
          <p className="footer-note">
            Upload a syllabus, learn each sub-topic with the tutor, then test yourself.
            The assessment adapts to how you answer and shows you exactly where you&apos;re weak.
          </p>
        </div>
      </footer>
    </>
  );
}

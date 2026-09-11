import { useCallback, useEffect, useRef, useState } from 'react';
import { pomodoro as pomodoroApi } from '../../lib/api';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { clock } from '../../lib/format';
import { Pause, Play, Stop, Timer } from '../../lib/icons';

/**
 * Focus session timer (PRD 7.8).
 * State machine: idle -> focusing -> (paused <-> focusing) -> complete -> idle.
 * The countdown runs client-side; the server is the record of what was logged.
 */
export default function PomodoroWidget({ subjectId, subtopicId }) {
  const { user } = useAuth();
  const toast = useToast();
  const planned = user?.pomodoro_minutes || 25;

  const [session, setSession] = useState(null); // server row
  const [elapsed, setElapsed] = useState(0); // focused seconds
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const finishing = useRef(false);

  const status = session?.status ?? 'idle';
  const target = (session?.planned_minutes || planned) * 60;
  const remaining = Math.max(0, target - elapsed);

  // Resume whatever the server still has open for this user.
  useEffect(() => {
    let alive = true;
    pomodoroApi
      .active()
      .then((row) => {
        if (!alive || !row) return;
        setSession(row);
        const since = (Date.now() - new Date(row.started_at).getTime()) / 1000;
        setElapsed(row.status === 'active' ? Math.max(0, Math.floor(since)) : (row.duration_minutes || 0) * 60);
      })
      .catch(() => {
        /* the timer is optional — never block the page on it */
      });
    return () => {
      alive = false;
    };
  }, []);

  // Tick only while focusing.
  useEffect(() => {
    if (status !== 'active') return undefined;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [status]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const finish = useCallback(
    async (completed) => {
      if (!session || finishing.current) return;
      finishing.current = true;
      setBusy(true);
      try {
        await pomodoroApi.stop(session.id, {
          completed,
          durationMinutes: Math.max(0, Math.round(elapsed / 60)),
        });
        toast.success(
          completed
            ? `Focus session logged: ${Math.round(elapsed / 60)} min.`
            : 'Session ended early.',
        );
      } catch (err) {
        toast.error(err);
      } finally {
        finishing.current = false;
        setBusy(false);
        setSession(null);
        setElapsed(0);
      }
    },
    [session, elapsed, toast],
  );

  // Auto-complete when the planned duration is reached.
  useEffect(() => {
    if (status === 'active' && elapsed >= target) finish(true);
  }, [status, elapsed, target, finish]);

  async function start() {
    setBusy(true);
    try {
      const row = await pomodoroApi.start({
        subject_id: subjectId || null,
        subtopic_id: subtopicId || null,
        planned_minutes: planned,
      });
      setSession(row);
      setElapsed(0);
      setOpen(true);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    if (!session) return;
    setBusy(true);
    try {
      const row =
        session.status === 'active'
          ? await pomodoroApi.pause(session.id)
          : await pomodoroApi.resume(session.id);
      setSession(row);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  const label = status === 'idle' ? 'Focus' : clock(remaining);
  const tone = status === 'active' ? 'run' : status === 'paused' ? 'paused' : '';

  return (
    <div className="pomo menu" ref={panelRef}>
      <button
        className={`pomo-clock ${tone}`}
        onClick={() => (status === 'idle' ? start() : setOpen((o) => !o))}
        disabled={busy}
        title={status === 'idle' ? `Start a ${planned}-minute focus session` : 'Focus session'}
        aria-label={status === 'idle' ? 'Start focus session' : `Focus session, ${label} remaining`}
      >
        {status === 'idle' ? <Timer style={{ width: 15, height: 15, margin: '0 auto' }} /> : label}
      </button>

      {open && status !== 'idle' && (
        <div className="pomo-panel">
          <h4>Focus session</h4>
          <p className="muted" style={{ fontSize: 12.5 }}>
            {status === 'paused' ? 'Paused' : 'Focusing'} · {planned} min planned
          </p>
          <p className="pomo-big">{clock(remaining)}</p>
          <div className="row gap8">
            <button className="btn btn-ghost btn-sm grow" onClick={toggle} disabled={busy}>
              {status === 'active' ? <Pause style={{ width: 14, height: 14 }} /> : <Play style={{ width: 14, height: 14 }} />}
              {status === 'active' ? 'Pause' : 'Resume'}
            </button>
            <button className="btn btn-danger btn-sm grow" onClick={() => finish(false)} disabled={busy}>
              <Stop style={{ width: 14, height: 14 }} />
              End
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

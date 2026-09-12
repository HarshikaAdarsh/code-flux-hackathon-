import { useCallback, useEffect, useRef, useState } from 'react';
import { teach as teachApi } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import Markdown from '../../components/Markdown';
import { useVoice } from './useVoice';
import { Brain, Cross, Mic, Send, Speaker, SpeakerOff, Stop } from '../../lib/icons';

/**
 * Topic-scoped teaching chat (PRD 7.2).
 *
 * Every turn carries subject_id + subtopic_id so the tutor stays inside the
 * syllabus, and lessons stream token-by-token (PRD section 11).
 *
 * Voice (PRD 7.5) goes through the same path as typing:
 *   mic -> /voice/transcribe -> the streaming turn -> /voice/speak
 * so a spoken question behaves exactly like a typed one.
 */
export default function TutorPanel({ subject, topic, subtopic, language, onAssess }) {
  const toast = useToast();
  const vc = useVoice();

  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState('');
  const [voiceOn, setVoiceOn] = useState(false);

  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const atBottom = useRef(true);
  const voiceOnRef = useRef(voiceOn);
  voiceOnRef.current = voiceOn;

  const started = messages.length > 0;
  const busy = streaming || vc.transcribing;

  /* --------------------------- history & scroll --------------------------- */

  useEffect(() => {
    abortRef.current?.();
    vc.stopAudio();
    vc.cancel();
    setMessages([]);
    setSessionId(null);
    setStreaming(false);
    setInput('');

    if (!subtopic) return undefined;
    let alive = true;
    teachApi
      .sessions({ subtopic_id: subtopic.id, limit: 1 })
      .then((rows) => {
        if (!alive || !rows?.length) return;
        setSessionId(rows[0].id);
        setMessages(rows[0].messages || []);
      })
      .catch(() => {
        /* no transcript yet just means a fresh lesson */
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtopic?.id]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !atBottom.current) return;
    // Instant while tokens arrive — a smooth animation restarted on every
    // token looks like lag. Smooth only for the occasional idle jump.
    el.scrollTo({
      top: el.scrollHeight,
      behavior: streaming ? 'auto' : 'smooth',
    });
  });

  useEffect(() => () => abortRef.current?.(), []);

  const onScroll = (e) => {
    const el = e.currentTarget;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  /* ------------------------------- sending ------------------------------- */

  const send = useCallback(
    (text, style = 'default') => {
      if (streaming) return;
      const clean = (text || '').trim();
      // An empty message is the "just teach me this sub-topic" opener.
      if (!clean && !subtopic) {
        toast.error('Pick a sub-topic first, or type a question.');
        return;
      }

      atBottom.current = true;
      setStreaming(true);
      setMessages((m) => [
        ...m,
        ...(clean ? [{ role: 'user', content: clean }] : []),
        { role: 'assistant', content: '', pending: true },
      ]);

      let full = '';
      let provider = null;
      // Track 1: the backend audits each sentence before it may be spoken.
      // `speak` holds the approved or corrected text, keyed by sentence index;
      // raw streamed text is never sent to text-to-speech.
      const audited = new Map();

      abortRef.current = teachApi.stream(
        {
          subject_id: subject?.id,
          subtopic_id: subtopic?.id,
          session_id: sessionId,
          message: clean || undefined,
          mode: 'text',
          language,
          style,
        },
        {
          onEvent: (ev) => {
            if (ev.type === 'session') {
              setSessionId(ev.session_id);
            } else if (ev.type === 'provider') {
              provider = ev.value;
            } else if (ev.type === 'token') {
              full += ev.value;
              setMessages((m) => {
                const next = [...m];
                next[next.length - 1] = { role: 'assistant', content: full, pending: true };
                return next;
              });
            } else if (ev.type === 'verified') {
              audited.set(ev.index, ev);
            } else if (ev.type === 'done') {
              const verdicts = [...audited.entries()]
                .sort((a, b) => a[0] - b[0])
                .map(([, v]) => v);
              const corrections = verdicts.filter((v) => v.note).map((v) => v.note);
              // Only audited text is ever spoken.
              const safeText = verdicts
                .map((v) => v.speak)
                .filter(Boolean)
                .join(' ')
                .trim();

              setMessages((m) => {
                const next = [...m];
                next[next.length - 1] = {
                  role: 'assistant',
                  content: full,
                  provider: provider || ev.provider,
                  corrections,
                };
                return next;
              });
              setStreaming(false);

              // Read the answer aloud when voice output is on (PRD 7.5).
              // Falls back to the raw reply only when nothing was audited at
              // all (auditing disabled or the auditor was unreachable).
              if (voiceOnRef.current) {
                const spoken = safeText || full;
                if (spoken) {
                  vc.speak(spoken, language).then((played) => {
                    if (!played) {
                      toast.show("Voice isn't available for this reply — showing the text.");
                    }
                  });
                }
              }
              if (corrections.length) {
                toast.show(
                  corrections.length === 1
                    ? '1 statement was corrected before being read aloud.'
                    : `${corrections.length} statements were corrected before being read aloud.`,
                );
              }
            } else if (ev.type === 'error') {
              toast.error(
                ev.value === 'providers_unavailable'
                  ? 'Both AI providers are unavailable right now. Try again in a moment.'
                  : 'The lesson stream was interrupted.',
              );
            }
          },
          onError: (err) => {
            setStreaming(false);
            setMessages((m) => m.filter((x) => !x.pending));
            toast.error(err);
          },
        },
      );
    },
    [streaming, subject?.id, subtopic?.id, sessionId, language, toast, vc],
  );

  function submit(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    send(text);
  }

  /* -------------------------------- voice -------------------------------- */

  /**
   * One tap starts recording, the next transcribes and sends.
   * The transcript is shown as the user's message, so what the tutor heard is
   * always visible — if Whisper mishears, you can see why the answer is odd.
   */
  const handleMic = useCallback(async () => {
    if (busy) return;

    if (vc.recording) {
      const blob = await vc.stop();
      try {
        const { text } = await vc.transcribe(blob, language);
        send(text);
      } catch (err) {
        toast.error(err.message);
      }
      return;
    }

    if (!vc.supported) {
      toast.error('This browser cannot record audio. Type your question instead.');
      return;
    }
    vc.stopAudio(); // don't record the tutor talking over you
    const ok = await vc.start();
    if (!ok) {
      toast.error('Microphone permission was denied. Allow it in your browser settings.');
    }
  }, [busy, vc, language, send, toast]);

  function toggleVoiceOut() {
    const next = !voiceOn;
    setVoiceOn(next);
    if (!next) vc.stopAudio();
    toast.show(next ? 'Voice on — replies will be read aloud.' : 'Voice off.');
  }

  /* ------------------------------- rendering ------------------------------ */

  const chips =
    subtopic && started && !busy && !vc.recording
      ? [
          { label: 'Explain simpler', style: 'simpler', text: 'Explain that again, simpler.' },
          { label: 'Give an example', style: 'example', text: 'Give me a worked example.' },
          { label: 'Summarise', style: 'summary', text: 'Give me a quick revision summary.' },
        ]
      : [];

  const orbState = vc.recording
    ? 'listening'
    : vc.speaking
      ? 'speaking'
      : busy
        ? 'thinking'
        : '';

  const micLabel = vc.recording
    ? 'Stop and send'
    : vc.transcribing
      ? 'Transcribing…'
      : 'Ask with your voice';

  const micIcon = vc.transcribing ? <span className="spinner" /> : vc.recording ? <Stop /> : <Mic />;

  return (
    <aside className="tutor-panel" aria-label="AI tutor">
      <div className="tutor-head">
        <h2>Tutor</h2>
        <span className="scope">
          {subtopic ? `${topic?.title} · ${subtopic.title}` : 'No sub-topic selected'}
        </span>
        {streaming && <span className="live">Live</span>}
        <button
          className="icon-btn"
          aria-pressed={voiceOn}
          onClick={toggleVoiceOut}
          title={voiceOn ? 'Replies are read aloud' : 'Replies are text only'}
          aria-label="Toggle spoken replies"
          type="button"
        >
          {voiceOn ? <Speaker /> : <SpeakerOff />}
        </button>
      </div>

      {!started ? (
        <div className="stage">
          <button
            className={`orb ${orbState}`}
            onClick={handleMic}
            disabled={busy}
            title={micLabel}
            aria-label={micLabel}
            type="button"
          >
            {micIcon}
          </button>

          {vc.recording ? (
            <>
              <p className="stage-title">Listening… {vc.seconds}s</p>
              <p className="stage-sub">Ask your question, then tap the square to send it.</p>
              <button className="btn btn-ghost btn-sm" onClick={vc.cancel} type="button">
                <Cross style={{ width: 14, height: 14 }} />
                Cancel
              </button>
            </>
          ) : subtopic ? (
            <>
              <p className="stage-title">{subtopic.title}</p>
              <p className="stage-sub">
                {topic?.title}. Tap the mic to ask out loud, or start the lesson and the
                tutor will teach it step by step.
              </p>
              <button
                className="btn btn-marker btn-lg"
                onClick={() => send('', 'default')}
                disabled={busy}
                type="button"
              >
                {subtopic.is_completed ? 'Revise this' : 'Start lesson'}
              </button>
            </>
          ) : (
            <>
              <p className="stage-title">What are we studying?</p>
              <p className="stage-sub">
                Pick a sub-topic from the syllabus on the left, or tap the mic and ask a
                question about {subject?.name || 'this subject'}.
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="transcript" ref={scrollRef} onScroll={onScroll}>
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div className="msg user" key={i}>
                {m.content}
              </div>
            ) : (
              <div className={`msg tutor${m.pending && m.content ? ' streaming' : ''}`} key={i}>
                {m.content ? (
                  <Markdown>{m.content}</Markdown>
                ) : (
                  <span className="typing" aria-label="Tutor is thinking">
                    <i /><i /><i />
                  </span>
                )}
                {m.corrections?.length > 0 && (
                  <div className="corrections" role="note">
                    <p className="corrections-head">
                      Fact check: {m.corrections.length} correction
                      {m.corrections.length > 1 ? 's' : ''}
                    </p>
                    <ul>
                      {m.corrections.map((c, k) => (
                        <li key={k}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {m.provider && m.provider !== 'none' && <p className="prov">via {m.provider}</p>}
              </div>
            ),
          )}

          {subtopic?.is_completed && !busy && (
            <div className="row gap8" style={{ alignSelf: 'stretch', marginTop: 4 }}>
              <button className="btn btn-ink btn-sm" onClick={() => onAssess(subtopic)} type="button">
                <Brain style={{ width: 14, height: 14 }} />
                Test me on this
              </button>
            </div>
          )}
        </div>
      )}

      <div className="chips">
        {chips.map((c) => (
          <button key={c.label} className="chip" onClick={() => send(c.text, c.style)} type="button">
            {c.label}
          </button>
        ))}
        {vc.speaking && (
          <button className="chip" onClick={vc.stopAudio} type="button">
            <Stop style={{ width: 13, height: 13 }} />
            Stop audio
          </button>
        )}
        {streaming && (
          <button
            className="chip"
            onClick={() => {
              abortRef.current?.();
              setStreaming(false);
              setMessages((m) => m.map((x) => (x.pending ? { ...x, pending: false } : x)));
            }}
            type="button"
          >
            <Stop style={{ width: 13, height: 13 }} />
            Stop
          </button>
        )}
      </div>

      <form className="dock" onSubmit={submit}>
        <button
          className={`orb orb-sm ${orbState}`}
          onClick={handleMic}
          disabled={busy}
          title={micLabel}
          aria-label={micLabel}
          type="button"
        >
          {micIcon}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            vc.recording
              ? `Listening… ${vc.seconds}s — tap the square to send`
              : vc.transcribing
                ? 'Working out what you said…'
                : subtopic
                  ? `Ask about ${subtopic.title}`
                  : 'Ask a question, or pick a sub-topic'
          }
          disabled={busy || vc.recording}
          aria-label="Message the tutor"
        />
        <button
          className="btn btn-ink"
          disabled={busy || vc.recording || !input.trim()}
          type="submit"
          aria-label="Send"
        >
          <Send style={{ width: 16, height: 16 }} />
        </button>
      </form>
    </aside>
  );
}

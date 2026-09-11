import { useCallback, useEffect, useRef, useState } from 'react';
import { teach as teachApi, voice as voiceApi } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import Markdown from '../../components/Markdown';
import { useVoice } from './useVoice';
import { Brain, Mic, Send, Speaker, SpeakerOff, Stop } from '../../lib/icons';

/**
 * Topic-scoped teaching chat (PRD 7.2).
 * Every turn carries subject_id + subtopic_id so the tutor stays inside the
 * syllabus. Lessons stream token-by-token (PRD section 11).
 */
export default function TutorPanel({ subject, topic, subtopic, language, onAssess }) {
  const toast = useToast();
  const vc = useVoice();

  const [messages, setMessages] = useState([]); // {role, content, provider}
  const [sessionId, setSessionId] = useState(null);
  const [streaming, setStreaming] = useState(false);
  const [pendingVoice, setPendingVoice] = useState(false);
  const [input, setInput] = useState('');
  const [voiceOn, setVoiceOn] = useState(false);

  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const bottomRef = useRef(true);

  const started = messages.length > 0;
  const busy = streaming || pendingVoice;

  /* --------------------------- history & scroll --------------------------- */

  // Load the existing transcript whenever the selected sub-topic changes.
  useEffect(() => {
    abortRef.current?.();
    vc.stopAudio();
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
        /* a missing transcript just means a fresh lesson */
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtopic?.id]);

  // Keep the transcript pinned to the bottom unless the user scrolled up.
  useEffect(() => {
    if (bottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  });

  const onScroll = (e) => {
    const el = e.currentTarget;
    bottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  useEffect(() => () => abortRef.current?.(), []);

  /* ------------------------------- sending ------------------------------- */

  const send = useCallback(
    (text, style = 'default') => {
      if (busy) return;
      const clean = (text || '').trim();
      if (!clean && !subtopic) return;

      bottomRef.current = true;
      setStreaming(true);
      setMessages((m) => [
        ...m,
        ...(clean ? [{ role: 'user', content: clean }] : []),
        { role: 'assistant', content: '', pending: true },
      ]);

      let full = '';
      let provider = null;

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
            } else if (ev.type === 'done') {
              setMessages((m) => {
                const next = [...m];
                next[next.length - 1] = {
                  role: 'assistant',
                  content: full,
                  provider: provider || ev.provider,
                };
                return next;
              });
              setStreaming(false);
              if (voiceOn && full) vc.speak(full, language);
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
    [busy, subject?.id, subtopic?.id, sessionId, language, voiceOn, toast, vc],
  );

  function submit(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    send(text);
  }

  /* -------------------------------- voice -------------------------------- */

  async function toggleMic() {
    if (vc.recording) {
      const blob = await vc.stop();
      if (!blob) {
        toast.error("That recording was too short — hold the mic a little longer.");
        return;
      }
      setPendingVoice(true);
      bottomRef.current = true;
      try {
        const res = await voiceApi.chat({
          blob,
          subjectId: subject?.id,
          subtopicId: subtopic?.id,
          sessionId,
          language,
          speakReply: true,
        });
        setSessionId(res.session_id);
        setMessages((m) => [
          ...m,
          { role: 'user', content: res.transcript },
          { role: 'assistant', content: res.reply, provider: res.provider },
        ]);
        if (res.audio_url) {
          await vc.playUrl(res.audio_url);
        } else {
          toast.show("Voice isn't available for that reply — showing the text instead.");
        }
      } catch (err) {
        toast.error(err);
      } finally {
        setPendingVoice(false);
      }
      return;
    }

    if (!vc.supported) {
      toast.error('Your browser cannot record audio. Type your question instead.');
      return;
    }
    const ok = await vc.start();
    if (!ok) toast.error('Microphone permission was denied.');
  }

  /* ------------------------------- rendering ------------------------------ */

  const chips = subtopic && started && !busy
    ? [
        { label: 'Explain simpler', style: 'simpler', text: 'Explain that again, simpler.' },
        { label: 'Give an example', style: 'example', text: 'Give me a worked example.' },
        { label: 'Summarise', style: 'summary', text: 'Give me a quick revision summary.' },
      ]
    : [];

  const orbState = vc.recording ? 'listening' : vc.speaking ? 'speaking' : busy ? 'thinking' : '';

  return (
    <aside className="tutor" aria-label="AI tutor">
      <div className="tutor-head">
        <h2>Tutor</h2>
        <span className="scope">
          {subtopic ? `${topic?.title} · ${subtopic.title}` : 'No sub-topic selected'}
        </span>
        {busy && <span className="live">Live</span>}
        <button
          className="icon-btn"
          aria-pressed={voiceOn}
          onClick={() => {
            const next = !voiceOn;
            setVoiceOn(next);
            if (!next) vc.stopAudio();
            toast.show(next ? 'Voice on — lessons will be read aloud.' : 'Voice off.');
          }}
          title={voiceOn ? 'Voice on' : 'Voice off'}
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
            onClick={() => (subtopic ? send('', 'default') : toggleMic())}
            disabled={busy || !subtopic}
            aria-label={subtopic ? `Start the lesson on ${subtopic.title}` : 'Select a sub-topic'}
            type="button"
          >
            {busy ? <span className="spinner" /> : <Mic />}
          </button>

          {subtopic ? (
            <>
              <p className="stage-title">{subtopic.title}</p>
              <p className="stage-sub">
                {topic?.title}. The tutor teaches this step by step, then checks you
                understood. Mark it done when you&apos;re ready to be tested.
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
                Pick a sub-topic from the syllabus on the left and the tutor will teach it.
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
              <div className="msg tutor" key={i}>
                {m.content ? <Markdown>{m.content}</Markdown> : (
                  <span className="typing" aria-label="Tutor is thinking">
                    <i /><i /><i />
                  </span>
                )}
                {m.provider && m.provider !== 'none' && (
                  <p className="prov">via {m.provider}</p>
                )}
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
          onClick={toggleMic}
          disabled={pendingVoice || streaming}
          title={vc.recording ? 'Stop and send' : 'Ask with your voice'}
          aria-label={vc.recording ? 'Stop recording and send' : 'Record a question'}
          type="button"
        >
          {pendingVoice ? <span className="spinner" /> : vc.recording ? <Stop /> : <Mic />}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            vc.recording
              ? 'Listening… tap the square to send'
              : subtopic
                ? `Ask about ${subtopic.title}`
                : 'Pick a sub-topic to begin'
          }
          disabled={busy || vc.recording}
          aria-label="Message the tutor"
        />
        <button className="btn btn-ink" disabled={busy || !input.trim()} type="submit" aria-label="Send">
          <Send style={{ width: 16, height: 16 }} />
        </button>
      </form>
    </aside>
  );
}

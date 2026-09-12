import { useCallback, useEffect, useRef, useState } from 'react';
import { fileUrl, voice as voiceApi } from '../../lib/api';

/**
 * Mic capture, speech-to-text and spoken playback (PRD 7.5).
 *
 * Flow, matching the PRD's API surface:
 *   record  -> POST /voice/transcribe  (Groq Whisper)  -> text
 *   text    -> the normal streaming tutor turn
 *   reply   -> POST /voice/speak                       -> audio
 *
 * Keeping STT separate from the tutor turn means voice input goes through the
 * same streaming path as typing: the student sees what was heard, can correct
 * it, and the answer streams in rather than arriving in one block.
 */

const MAX_SECONDS = 60; // hard stop so a forgotten mic can't record forever
const MIN_BYTES = 1200; // below this the clip is almost certainly silence

export function useVoice() {
  const [supported, setSupported] = useState(true);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const audioRef = useRef(null);
  const resolveRef = useRef(null);
  const tickRef = useRef(null);

  useEffect(() => {
    setSupported(
      typeof window !== 'undefined' &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof window.MediaRecorder !== 'undefined',
    );
  }, []);

  const releaseMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    clearInterval(tickRef.current);
    tickRef.current = null;
  }, []);

  /** Begin capture. Resolves false if the mic is unavailable or denied. */
  const start = useCallback(async () => {
    if (!supported || recorderRef.current?.state === 'recording') return false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      // Pick a container the browser supports; Whisper accepts all of these.
      const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = candidates.find((m) => window.MediaRecorder.isTypeSupported?.(m));

      const rec = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      rec.ondataavailable = (e) => {
        if (e.data?.size) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const type = rec.mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type });
        releaseMic();
        setRecording(false);
        setSeconds(0);
        resolveRef.current?.(blob.size >= MIN_BYTES ? blob : null);
        resolveRef.current = null;
      };

      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setSeconds(0);

      tickRef.current = setInterval(() => {
        setSeconds((s) => {
          if (s + 1 >= MAX_SECONDS) {
            try {
              rec.stop();
            } catch {
              /* already stopped */
            }
          }
          return s + 1;
        });
      }, 1000);

      return true;
    } catch {
      releaseMic();
      setRecording(false);
      return false;
    }
  }, [supported, releaseMic]);

  /** Stop capture; resolves with the blob, or null if it was too short. */
  const stop = useCallback(
    () =>
      new Promise((resolve) => {
        const rec = recorderRef.current;
        if (!rec || rec.state === 'inactive') {
          resolve(null);
          return;
        }
        resolveRef.current = resolve;
        rec.stop();
      }),
    [],
  );

  /** Abandon a recording without transcribing it. */
  const cancel = useCallback(() => {
    const rec = recorderRef.current;
    resolveRef.current = null;
    if (rec && rec.state !== 'inactive') {
      rec.onstop = null;
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
    releaseMic();
    setRecording(false);
    setSeconds(0);
  }, [releaseMic]);

  /**
   * Speech to text via POST /voice/transcribe.
   * Returns {text, language} or throws with a message worth showing.
   */
  const transcribe = useCallback(async (blob, language) => {
    if (!blob) throw new Error('Nothing was recorded — hold the mic a little longer.');
    setTranscribing(true);
    try {
      const ext = (blob.type.split('/')[1] || 'webm').split(';')[0];
      const result = await voiceApi.transcribe({
        blob,
        language,
        filename: `speech.${ext}`,
      });
      const text = (result?.text || '').trim();
      if (!text) throw new Error("I couldn't make out any words in that recording.");
      return { text, language: result.language || language };
    } finally {
      setTranscribing(false);
    }
  }, []);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const playUrl = useCallback(
    (url) =>
      new Promise((resolve) => {
        if (!url) {
          resolve(false);
          return;
        }
        stopAudio();
        const audio = new Audio(fileUrl(url));
        audioRef.current = audio;
        setSpeaking(true);
        const done = (okay) => {
          if (audioRef.current === audio) {
            audioRef.current = null;
            setSpeaking(false);
          }
          resolve(okay);
        };
        audio.onended = () => done(true);
        audio.onerror = () => done(false);
        audio.play().catch(() => done(false)); // autoplay can be blocked
      }),
    [stopAudio],
  );

  /**
   * Text to speech via POST /voice/speak.
   * Returns false when the backend reports voice_enabled:false, so the caller
   * can fall back to text rather than failing silently (PRD section 11).
   */
  const speak = useCallback(
    async (text, language) => {
      if (!text?.trim()) return false;
      try {
        const res = await voiceApi.speak({ text, language });
        if (!res?.voice_enabled || !res.audio_url) return false;
        return await playUrl(res.audio_url);
      } catch {
        return false;
      }
    },
    [playUrl],
  );

  useEffect(
    () => () => {
      cancel();
      stopAudio();
    },
    [cancel, stopAudio],
  );

  return {
    supported, recording, seconds, transcribing, speaking,
    start, stop, cancel, transcribe, speak, playUrl, stopAudio,
  };
}

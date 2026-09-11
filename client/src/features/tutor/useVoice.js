import { useCallback, useEffect, useRef, useState } from 'react';
import { fileUrl, voice as voiceApi } from '../../lib/api';

/**
 * Mic capture + spoken playback for the voice assistant (PRD 7.5).
 * Recording uses MediaRecorder; the resulting blob goes to /voice/chat, which
 * runs STT -> tutor -> TTS in one round trip.
 */
export function useVoice() {
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [supported, setSupported] = useState(true);

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const audioRef = useRef(null);
  const resolveRef = useRef(null);

  useEffect(() => {
    setSupported(
      typeof window !== 'undefined' &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof window.MediaRecorder !== 'undefined',
    );
  }, []);

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  /** Begin capture. Resolves false if the mic is unavailable or denied. */
  const start = useCallback(async () => {
    if (!supported || recording) return false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      // Pick a mime the browser actually supports; Whisper accepts all of these.
      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = preferred.find((m) => window.MediaRecorder.isTypeSupported?.(m));

      const rec = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      rec.ondataavailable = (e) => {
        if (e.data?.size) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const type = rec.mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type });
        cleanupStream();
        setRecording(false);
        resolveRef.current?.(blob.size > 800 ? blob : null);
        resolveRef.current = null;
      };

      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      return true;
    } catch {
      cleanupStream();
      setRecording(false);
      return false;
    }
  }, [supported, recording, cleanupStream]);

  /** Stop capture and resolve with the recorded blob (or null if too short). */
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

  const cancel = useCallback(() => {
    const rec = recorderRef.current;
    resolveRef.current = null;
    if (rec && rec.state !== 'inactive') {
      rec.onstop = null;
      rec.stop();
    }
    cleanupStream();
    setRecording(false);
  }, [cleanupStream]);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    setSpeaking(false);
  }, []);

  /** Play an audio URL returned by the backend. */
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
        const done = (ok) => {
          if (audioRef.current === audio) {
            audioRef.current = null;
            setSpeaking(false);
          }
          resolve(ok);
        };
        audio.onended = () => done(true);
        audio.onerror = () => done(false);
        audio.play().catch(() => done(false)); // autoplay can be blocked
      }),
    [stopAudio],
  );

  /**
   * Synthesize text and play it. Returns false when the backend reports
   * voice_enabled:false so the caller can fall back to text (PRD section 11).
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

  return { supported, recording, speaking, start, stop, cancel, speak, playUrl, stopAudio };
}

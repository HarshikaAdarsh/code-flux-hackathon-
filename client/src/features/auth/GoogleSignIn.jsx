import { useEffect, useRef, useState } from 'react';
import { GOOGLE_CLIENT_ID } from '../../lib/api';

/**
 * Google sign-in (PRD 7.7 / §10: "JWT + OAuth (Google)").
 *
 * Uses Google Identity Services. The browser hands us an ID token, which the
 * backend verifies at /auth/google before issuing our own JWT — the Google
 * credential never becomes the session.
 *
 * Renders nothing when VITE_GOOGLE_CLIENT_ID is unset, so email/password
 * remains the whole story until someone configures OAuth.
 */
const SCRIPT_SRC = 'https://accounts.google.com/gsi/client';

function loadScript() {
  if (window.google?.accounts?.id) return Promise.resolve(true);

  const existing = document.querySelector(`script[src="${SCRIPT_SRC}"]`);
  if (existing) {
    return new Promise((resolve) => {
      existing.addEventListener('load', () => resolve(true));
      existing.addEventListener('error', () => resolve(false));
    });
  }

  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

export default function GoogleSignIn({ onCredential, disabled }) {
  const holder = useRef(null);
  const [failed, setFailed] = useState(false);

  // Keep the latest callback without re-initialising the Google client.
  const callbackRef = useRef(onCredential);
  callbackRef.current = onCredential;

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return undefined;
    let alive = true;

    loadScript().then((loaded) => {
      if (!alive) return;
      if (!loaded || !window.google?.accounts?.id) {
        setFailed(true);
        return;
      }
      try {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (response) => callbackRef.current?.(response.credential),
        });
        window.google.accounts.id.renderButton(holder.current, {
          theme: 'outline',
          size: 'large',
          width: 320,
          text: 'continue_with',
          shape: 'rectangular',
        });
      } catch {
        setFailed(true);
      }
    });

    return () => {
      alive = false;
    };
  }, []);

  if (!GOOGLE_CLIENT_ID) return null;

  return (
    <div style={{ marginBottom: 18 }}>
      <div
        ref={holder}
        style={{
          display: 'flex',
          justifyContent: 'center',
          opacity: disabled ? 0.5 : 1,
          pointerEvents: disabled ? 'none' : 'auto',
        }}
      />
      {failed && (
        <p className="muted" style={{ fontSize: 12.5, textAlign: 'center', marginTop: 6 }}>
          Google sign-in couldn&apos;t load. Use your email and password below.
        </p>
      )}
      <div className="divider">
        <span />
        or
        <span />
      </div>
    </div>
  );
}

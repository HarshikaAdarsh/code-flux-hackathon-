import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { auth as authApi, getToken, setToken } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  // Restore the session from a stored JWT on first load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken()) {
        setReady(true);
        return;
      }
      try {
        const me = await authApi.me();
        if (!cancelled) setUser(me);
      } catch {
        setToken(null); // expired or revoked
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const adopt = useCallback((payload) => {
    setToken(payload.access_token);
    setUser(payload.user);
    return payload.user;
  }, []);

  const login = useCallback(
    async (email, password) => adopt(await authApi.login({ email, password })),
    [adopt],
  );

  const signup = useCallback(
    async (payload) => adopt(await authApi.signup(payload)),
    [adopt],
  );

  const loginWithGoogle = useCallback(
    async (idToken) => adopt(await authApi.google(idToken)),
    [adopt],
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const updateProfile = useCallback(async (patch) => {
    const next = await authApi.updateMe(patch);
    setUser(next);
    return next;
  }, []);

  const value = useMemo(
    () => ({
      user, ready, login, signup, loginWithGoogle, logout, updateProfile,
      language: user?.preferred_language || 'en',
    }),
    [user, ready, login, signup, loginWithGoogle, logout, updateProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
};

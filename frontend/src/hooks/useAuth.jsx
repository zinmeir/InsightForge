import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, loadSession, onUnauthorized, saveSession } from '../api/client.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => loadSession());
  const [authDisabled, setAuthDisabled] = useState(false);
  const [checking, setChecking] = useState(!loadSession());

  const logout = useCallback(() => {
    saveSession(null);
    setSession(null);
  }, []);

  // If the backend runs with AUTH_ENABLED=false, /auth/me works without a token.
  useEffect(() => {
    if (session) return;
    api('/api/v1/auth/me')
      .then((me) => {
        if (me.auth_method === 'disabled') {
          setAuthDisabled(true);
          setSession({ token: '', username: 'anonymous', role: 'admin', expiresAt: Infinity });
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [session]);

  useEffect(() => onUnauthorized(logout), [logout]);

  // Log out when the token expires.
  useEffect(() => {
    if (!session || !Number.isFinite(session.expiresAt)) return undefined;
    const t = setTimeout(logout, Math.max(0, session.expiresAt - Date.now()));
    return () => clearTimeout(t);
  }, [session, logout]);

  const login = useCallback(async (username, password) => {
    const res = await api('/api/v1/auth/login', { method: 'POST', body: { username, password } });
    const next = {
      token: res.access_token,
      username: res.username,
      role: res.role,
      expiresAt: Date.now() + res.expires_in * 1000,
    };
    saveSession(next);
    setSession(next);
  }, []);

  const value = useMemo(
    () => ({
      session,
      user: session ? { username: session.username, role: session.role } : null,
      isAdmin: session?.role === 'admin',
      authDisabled,
      checking,
      login,
      logout,
    }),
    [session, authDisabled, checking, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

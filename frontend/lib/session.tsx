'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { UNAUTHORIZED_EVENT, getSession, logout as apiLogout, type SessionUser } from './api';

type SessionState = {
  user: SessionUser | null;
  loading: boolean;
  refresh: () => Promise<SessionUser | null>;
  logout: () => Promise<void>;
};

const SessionContext = createContext<SessionState>({
  user: null,
  loading: true,
  refresh: async () => null,
  logout: async () => {},
});

/**
 * Сессия пользователя. Токен лежит в HttpOnly-cookie, поэтому «залогинен ли
 * пользователь» определяется запросом /api/me, а не чтением localStorage.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const loaded = await getSession(true);
    setUser(loaded);
    setLoading(false);
    return loaded;
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <SessionContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  return useContext(SessionContext);
}

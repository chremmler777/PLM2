/**
 * AuthContext — identity from the shared SSO cookie via /auth/me.
 */
import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import client from '../api/client';

interface AuthContextType {
  userId: number | null;
  username: string | null;
  role: string | null;
  roles: string[];
  isAuthenticated: boolean;
  isAdmin: boolean;
  loading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/** One /auth/me in flight at a time: StrictMode's double effect (and any
 *  remount while it runs) shares the request instead of sending another. */
type MeResponse = { username?: string | null; user_id?: number | null; plm2_roles?: string[] };
let meInFlight: Promise<{ data: MeResponse }> | null = null;
function fetchMe(): Promise<{ data: MeResponse }> {
  if (!meInFlight) {
    const p = client.get<MeResponse>('/v1/auth/me');
    meInFlight = p;
    const release = () => { if (meInFlight === p) meInFlight = null; };
    p.then(release, release);
  }
  return meInFlight;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((res) => {
        if (!active) return;
        setUsername(res.data.username ?? null);
        setUserId(res.data.user_id ?? null);
        setRoles(res.data.plm2_roles ?? []);
        setIsAuthenticated(true);
      })
      .catch(() => {
        if (active) setIsAuthenticated(false);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const logout = useCallback(() => {
    window.location.href = '/';
  }, []);

  const isAdmin = roles.includes('plm2_Admin');
  const role = isAdmin ? 'admin' : isAuthenticated ? 'viewer' : null;

  const value: AuthContextType = {
    userId,
    username,
    role,
    roles,
    isAuthenticated,
    isAdmin,
    loading,
    logout,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

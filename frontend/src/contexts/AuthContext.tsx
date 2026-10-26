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
  /** May write at all: admin, or engineer (member of an active department).
   *  A viewer is read-only — the backend answers every write 403 — so no
   *  write control should be offered. Department gates still apply on top. */
  canWrite: boolean;
  /** Which prices the viewer reads (R23, /auth/me): all (admin, PM, Sales,
   *  Management), led (only the changes they lead), none. Null while loading. */
  priceView: 'all' | 'led' | 'none' | null;
  /** D-cost (/auth/me): reads the cost sheet (admin, Project Manager, Sales,
   *  Finance, Management; acts-as aware). The nav item and page go by it. */
  canReadCostSheet: boolean;
  /** Act as a person: the person the admin currently sees PLM as (null = themselves). */
  actingAsUser: { id: number; name: string } | null;
  /** The token holds plm2_Admin: may use the act-as switch, also while acting as a person. */
  realAdmin: boolean;
  loading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/** One /auth/me in flight at a time: StrictMode's double effect (and any
 *  remount while it runs) shares the request instead of sending another. */
type MeResponse = {
  username?: string | null; user_id?: number | null; plm2_roles?: string[];
  /** Local role: admin | engineer | viewer (engineer = department member). */
  role?: string | null;
  price_view?: 'all' | 'led' | 'none' | null;
  can_read_cost_sheet?: boolean;
  acting_as_user?: { id: number; name: string } | null;
};
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
  const [localRole, setLocalRole] = useState<string | null>(null);
  const [priceView, setPriceView] = useState<AuthContextType['priceView']>(null);
  const [canReadCostSheet, setCanReadCostSheet] = useState(false);
  const [actingAsUser, setActingAsUser] = useState<AuthContextType['actingAsUser']>(null);
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
        setLocalRole(res.data.role ?? null);
        setPriceView(res.data.price_view ?? null);
        setCanReadCostSheet(res.data.can_read_cost_sheet === true);
        setActingAsUser(res.data.acting_as_user ?? null);
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

  const realAdmin = roles.includes('plm2_Admin');
  // acting as a person: the UI is that person's (their role, never admin)
  const isAdmin = realAdmin && actingAsUser === null;
  const role = isAdmin ? 'admin'
    : !isAuthenticated ? null
    : localRole === 'engineer' ? 'engineer' : 'viewer';
  const canWrite = role === 'admin' || role === 'engineer';

  const value: AuthContextType = {
    userId,
    username,
    role,
    roles,
    isAuthenticated,
    isAdmin,
    canWrite,
    priceView,
    canReadCostSheet,
    actingAsUser,
    realAdmin,
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

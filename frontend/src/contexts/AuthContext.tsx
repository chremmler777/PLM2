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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    client
      .get('/v1/auth/me')
      .then((res) => {
        if (!active) return;
        setUsername(res.data.username ?? null);
        setUserId(res.data.sub ? Number(res.data.sub) : null);
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

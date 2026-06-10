/**
 * AuthContext - Authentication state management
 */

import React, { createContext, useContext, useState, useCallback } from 'react';

interface AuthContextType {
  token: string | null;
  userId: number | null;
  username: string | null;
  role: string | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (token: string, userId: number, username?: string, role?: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Initialize from localStorage
  const getInitialToken = () => localStorage.getItem('access_token');
  const getInitialUserId = () => {
    const id = localStorage.getItem('user_id');
    return id ? parseInt(id, 10) : null;
  };

  const [token, setToken] = useState<string | null>(getInitialToken);
  const [userId, setUserId] = useState<number | null>(getInitialUserId);
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem('username'));
  const [role, setRole] = useState<string | null>(() => localStorage.getItem('role'));

  const login = useCallback((newToken: string, newUserId: number, newUsername?: string, newRole?: string) => {
    localStorage.setItem('access_token', newToken);
    localStorage.setItem('user_id', newUserId.toString());
    if (newUsername) localStorage.setItem('username', newUsername);
    if (newRole) localStorage.setItem('role', newRole);
    setToken(newToken);
    setUserId(newUserId);
    setUsername(newUsername ?? null);
    setRole(newRole ?? null);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_id');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
    setToken(null);
    setUserId(null);
    setUsername(null);
    setRole(null);
  }, []);

  const value: AuthContextType = {
    token,
    userId,
    username,
    role,
    isAuthenticated: !!token,
    isAdmin: role === 'admin',
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

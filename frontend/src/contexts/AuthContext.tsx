/**
 * AuthContext - Authentication state management
 */

import React, { createContext, useContext, useState, useCallback } from 'react';

interface AuthContextType {
  token: string | null;
  userId: number | null;
  isAuthenticated: boolean;
  login: (token: string, userId: number) => void;
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

  const login = useCallback((newToken: string, newUserId: number) => {
    console.log('Login called with:', { newToken, newUserId });
    localStorage.setItem('access_token', newToken);
    localStorage.setItem('user_id', newUserId.toString());
    setToken(newToken);
    setUserId(newUserId);
    console.log('Auth state updated:', { token: newToken, userId: newUserId });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_id');
    setToken(null);
    setUserId(null);
  }, []);

  const value: AuthContextType = {
    token,
    userId,
    isAuthenticated: !!token,
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

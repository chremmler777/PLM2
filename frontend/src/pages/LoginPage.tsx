/**
 * LoginPage - Simple login for testing (Phase 6 will have proper auth)
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import client from '../api/client';
import { toast } from 'sonner';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      // Call backend login API using client
      const response = await client.post('/v1/auth/login', {
        email,
        password,
      });

      const data = response.data;
      console.log('Login successful:', { token: data.access_token, userId: data.user_id });

      // Update auth state with token from backend
      login(data.access_token, data.user_id);
      toast.success('Logged in successfully!');

      // Navigate after state update
      setTimeout(() => {
        navigate('/projects');
      }, 500);
    } catch (error: any) {
      console.error('Login error:', error);
      const errorMsg = error.response?.data?.detail || 'Invalid credentials';
      toast.error(errorMsg || 'Invalid credentials (test: test@example.com / password)');
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center">
      <div className="bg-slate-800 rounded-lg shadow-xl p-8 max-w-md w-full">
        <h1 className="text-3xl font-bold text-slate-100 mb-2">PLM System</h1>
        <p className="text-slate-300 mb-6">Product Lifecycle Management</p>

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-200 mb-1">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2 border border-slate-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="test@example.com"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-200 mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2 border border-slate-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="password"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 font-medium mt-6"
          >
            {isLoading ? 'Logging in...' : 'Log In'}
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-slate-600">
          <p className="text-xs text-slate-300 text-center">
            For Phase 1 testing: test@example.com / password
          </p>
        </div>
      </div>
    </div>
  );
}

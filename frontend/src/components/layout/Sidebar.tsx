/**
 * Sidebar - Main navigation component with collapse/expand
 */

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import ChangePasswordModal from '../ChangePasswordModal';
import SearchBox from '../SearchBox';
import NotificationBell from '../NotificationBell';
import client from '../../api/client';

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, username, role, isAdmin } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);

  const { data: taskCount } = useQuery<{ count: number }>({
    queryKey: ['open-task-count'],
    queryFn: async () => (await client.get('/v1/workflow-instances/open-task-count')).data,
    refetchInterval: 60_000,
  });
  const openTasks = taskCount?.count ?? 0;

  const navItems = [
    { path: '/dashboard', label: 'Dashboard', icon: '🏠' },
    { path: '/projects', label: 'Projects', icon: '📁' },
    { path: '/catalog', label: 'Purchased Parts', icon: '🛒' },
    { path: '/my-tasks', label: 'My Tasks', icon: '✅' },
    { path: '/workflows', label: 'Workflows', icon: '⚙️' },
    ...(isAdmin ? [{ path: '/users', label: 'Users', icon: '👥' }] : []),
  ];

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className={`bg-slate-800 border-r border-slate-700 min-h-screen flex flex-col transition-all ${
      isCollapsed ? 'w-20' : 'w-64'
    }`}>
      {/* Logo / Collapse Button */}
      <div className="p-4 border-b border-slate-700 flex items-center justify-between">
        {!isCollapsed && (
          <div>
            <h1 className="text-2xl font-bold text-slate-100">PLM v2</h1>
            <p className="text-xs text-slate-400 mt-1">Product Lifecycle</p>
          </div>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-1 hover:bg-slate-700 rounded transition text-slate-300 hover:text-slate-100"
          title={isCollapsed ? 'Expand' : 'Collapse'}
        >
          {isCollapsed ? '▶' : '◀'}
        </button>
      </div>

      {/* Search */}
      {!isCollapsed && (
        <div className="p-2 border-b border-slate-700">
          <SearchBox />
        </div>
      )}

      {/* Navigation Items */}
      <nav className="flex-1 p-2 space-y-2">
        {navItems.map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className={`w-full text-left px-3 py-3 rounded-lg transition font-medium ${
              isCollapsed ? 'justify-center' : ''
            } flex items-center gap-3 ${
              isActive(item.path)
                ? 'bg-blue-600 text-white'
                : 'text-slate-300 hover:bg-slate-700'
            }`}
            title={isCollapsed ? item.label : ''}
          >
            <span className="text-lg flex-shrink-0">{item.icon}</span>
            {!isCollapsed && <span className="flex-1">{item.label}</span>}
            {item.path === '/my-tasks' && openTasks > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-amber-500 text-slate-900 text-xs font-bold flex-shrink-0">
                {openTasks}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* User block + Logout */}
      <div className="p-2 border-t border-slate-700 space-y-2">
        {username && (
          <div className={`flex items-center gap-2 px-2 py-1.5 ${isCollapsed ? 'justify-center' : ''}`}>
            <div
              className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold flex-shrink-0"
              title={username}
            >
              {username.charAt(0).toUpperCase()}
            </div>
            {!isCollapsed && (
              <div className="min-w-0">
                <p className="text-sm text-slate-200 font-medium truncate">{username}</p>
                {role && <p className="text-xs text-slate-400 capitalize">{role}</p>}
              </div>
            )}
          </div>
        )}
        <NotificationBell collapsed={isCollapsed} />
        <button
          onClick={() => setShowChangePassword(true)}
          className="w-full px-3 py-2 rounded-lg text-slate-300 hover:bg-slate-700 font-medium text-sm text-left"
          title="Change password"
        >
          {isCollapsed ? '🔑' : '🔑 Change Password'}
        </button>
        <button
          onClick={logout}
          className="w-full px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium text-sm"
          title={isCollapsed ? 'Logout' : ''}
        >
          {isCollapsed ? '↪' : 'Logout'}
        </button>
      </div>

      {showChangePassword && <ChangePasswordModal onClose={() => setShowChangePassword(false)} />}
    </div>
  );
}

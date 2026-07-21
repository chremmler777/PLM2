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
    { path: '/suppliers', label: 'Suppliers', icon: '🏭' },
    { path: '/lessons', label: 'Lessons Learned', icon: '📘' },
    { path: '/changes', label: 'Changes', icon: '🔄' },
    { path: '/reports', label: 'Reports', icon: '📊' },
    { path: '/my-tasks', label: 'My Tasks', icon: '✅' },
    { path: '/workflows', label: 'Workflows', icon: '⚙️' },
    ...(isAdmin ? [{ path: '/users', label: 'Users', icon: '👥' }] : []),
  ];

  const isActive = (path: string) => location.pathname === path;

  return (
    <aside className={`bg-slate-800/80 border-r border-slate-700/70 min-h-screen flex flex-col transition-all duration-200 ${
      isCollapsed ? 'w-20' : 'w-64'
    }`}>
      {/* Logo / Collapse Button */}
      <div className="p-4 border-b border-slate-700/70 flex items-center justify-between">
        {!isCollapsed && (
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 shadow-lift flex items-center justify-center text-white font-bold text-lg select-none">
              P
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-100 tracking-tight leading-none">PLM v2</h1>
              <p className="text-[11px] text-slate-500 mt-1">Product lifecycle</p>
            </div>
          </div>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-1.5 hover:bg-slate-700 rounded-md text-slate-400 hover:text-slate-100"
          title={isCollapsed ? 'Expand' : 'Collapse'}
        >
          {isCollapsed ? '▶' : '◀'}
        </button>
      </div>

      {/* Search */}
      {!isCollapsed && (
        <div className="p-2 border-b border-slate-700/70">
          <SearchBox />
        </div>
      )}

      {/* Navigation Items */}
      <nav className="flex-1 p-2 space-y-0.5">
        {navItems.map((item) => {
          const active = isActive(item.path);
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              aria-current={active ? 'page' : undefined}
              className={`relative w-full text-left px-3 py-2.5 rounded-md text-sm font-medium ${
                isCollapsed ? 'justify-center' : ''
              } flex items-center gap-3 ${
                active
                  ? 'bg-sky-500/10 text-sky-300'
                  : 'text-slate-400 hover:bg-slate-700/60 hover:text-slate-200 hover:translate-x-0.5'
              }`}
              title={isCollapsed ? item.label : ''}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-full bg-sky-400" />
              )}
              <span className={`text-base flex-shrink-0 ${active ? '' : 'opacity-80'}`}>{item.icon}</span>
              {!isCollapsed && <span className="flex-1">{item.label}</span>}
              {item.path === '/my-tasks' && openTasks > 0 && (
                <span className="px-1.5 py-0.5 rounded-md bg-amber-500 text-slate-900 text-xs font-bold flex-shrink-0">
                  {openTasks}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* User block + Logout */}
      <div className="p-2 border-t border-slate-700/70 space-y-1">
        {username && (
          <div className={`flex items-center gap-2.5 px-2 py-2 ${isCollapsed ? 'justify-center' : ''}`}>
            <div
              className="w-8 h-8 rounded-lg bg-gradient-to-br from-slate-600 to-slate-700 text-slate-100 flex items-center justify-center text-sm font-semibold flex-shrink-0 ring-1 ring-slate-600"
              title={username}
            >
              {username.charAt(0).toUpperCase()}
            </div>
            {!isCollapsed && (
              <div className="min-w-0">
                <p className="text-sm text-slate-200 font-medium truncate leading-tight">{username}</p>
                {role && <p className="text-[11px] text-slate-500 capitalize">{role}</p>}
              </div>
            )}
          </div>
        )}
        <NotificationBell collapsed={isCollapsed} />
        <button
          onClick={() => setShowChangePassword(true)}
          className="w-full px-3 py-2 rounded-md text-slate-400 hover:bg-slate-700/60 hover:text-slate-200 font-medium text-sm text-left"
          title="Change password"
        >
          {isCollapsed ? '🔑' : '🔑 Change password'}
        </button>
        <button
          onClick={logout}
          className="w-full px-3 py-2 rounded-md border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-300 hover:bg-red-500/10 font-medium text-sm"
          title={isCollapsed ? 'Logout' : ''}
        >
          {isCollapsed ? '↪' : 'Logout'}
        </button>
      </div>

      {showChangePassword && <ChangePasswordModal onClose={() => setShowChangePassword(false)} />}
    </aside>
  );
}

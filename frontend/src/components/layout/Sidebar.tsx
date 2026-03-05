/**
 * Sidebar - Main navigation component with collapse/expand
 */

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const navItems = [
    { path: '/projects', label: 'Projects', icon: '📁' },
    { path: '/catalog', label: 'Purchased Parts', icon: '🛒' },
    { path: '/my-tasks', label: 'My Tasks', icon: '✅' },
    { path: '/workflows', label: 'Workflows', icon: '⚙️' },
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
            {!isCollapsed && <span>{item.label}</span>}
          </button>
        ))}
      </nav>

      {/* Logout */}
      <div className="p-2 border-t border-slate-700">
        <button
          onClick={logout}
          className="w-full px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium text-sm"
          title={isCollapsed ? 'Logout' : ''}
        >
          {isCollapsed ? '↪' : 'Logout'}
        </button>
      </div>
    </div>
  );
}

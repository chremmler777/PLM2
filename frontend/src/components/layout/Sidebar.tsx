/**
 * Sidebar - Main navigation component with collapse/expand.
 *
 * On a project page it starts as a 48 px icon rail so the items list and the
 * detail get the width; the choice made there is remembered per browser.
 * Everywhere else it starts expanded, as before, and is not remembered.
 */

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import SearchBox from '../SearchBox';
import NotificationBell from '../NotificationBell';
import { useOpenTaskCount } from '../../hooks/queries/useOpenTaskCount';
import { readStored, writeStored } from '../../lib/safeStorage';
import ActsAsSwitch from './ActsAsSwitch';

const RAIL_KEY = 'plm2.sidebar.projectRail';

function isProjectPage(path: string): boolean {
  return /^\/projects\/\d+(\/|$)/.test(path);
}

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, username, role } = useAuth();
  const onProjectPage = isProjectPage(location.pathname);
  // Anything but an explicit "expanded" (missing, garbage, unreadable) means the rail.
  const [railCollapsed, setRailCollapsed] = useState(() => readStored(RAIL_KEY) !== 'expanded');
  const [pageCollapsed, setPageCollapsed] = useState(false);
  const isCollapsed = onProjectPage ? railCollapsed : pageCollapsed;

  const toggleCollapsed = () => {
    if (onProjectPage) {
      const next = !railCollapsed;
      setRailCollapsed(next);
      writeStored(RAIL_KEY, next ? 'collapsed' : 'expanded');
    } else {
      setPageCollapsed(!pageCollapsed);
    }
  };

  // Workflow tasks + change tasks: whatever My Tasks would show.
  const openTasks = useOpenTaskCount();

  const dailyItems = [
    { path: '/dashboard', label: 'Dashboard', icon: '🏠' },
    { path: '/projects', label: 'Projects', icon: '📁' },
    { path: '/catalog', label: 'Purchased Parts', icon: '🛒' },
    { path: '/paints', label: 'Paints', icon: '🎨' },
    { path: '/suppliers', label: 'Suppliers', icon: '🏭' },
    { path: '/lessons', label: 'Lessons Learned', icon: '📘' },
    { path: '/changes', label: 'Changes', icon: '🔄' },
    { path: '/process-map', label: 'Process Flow', icon: '🗺️' },
    { path: '/pnl', label: 'P&L', icon: '💰' },
    { path: '/reports', label: 'Reports', icon: '📊' },
    { path: '/my-tasks', label: 'My Tasks', icon: '✅' },
  ];

  const setupItems = [
    { path: '/workflows', label: 'Workflows', icon: '⚙️' },
  ];

  const showSetup = role === 'admin' || role === 'engineer';

  const isActive = (path: string) => location.pathname === path;

  const renderNavItem = (item: { path: string; label: string; icon: string }) => {
    const active = isActive(item.path);
    return (
      <button
        key={item.path}
        onClick={() => navigate(item.path)}
        aria-current={active ? 'page' : undefined}
        aria-label={isCollapsed ? item.label : undefined}
        className={`relative w-full text-left py-2.5 rounded-md text-sm font-medium ${
          isCollapsed ? 'justify-center px-0' : 'px-3'
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
          <span className={isCollapsed
            ? 'absolute top-0.5 right-0.5 min-w-[1rem] px-1 rounded bg-amber-500 text-slate-900 text-[10px] leading-4 font-bold text-center'
            : 'px-1.5 py-0.5 rounded-md bg-amber-500 text-slate-900 text-xs font-bold flex-shrink-0'}>
            {openTasks}
          </span>
        )}
      </button>
    );
  };

  return (
    <aside
      data-testid="sidebar"
      data-collapsed={isCollapsed ? 'true' : 'false'}
      className={`bg-slate-800/80 border-r border-slate-700/70 min-h-screen flex flex-col flex-shrink-0 transition-all duration-200 ${
        isCollapsed ? 'w-12' : 'w-64'
      }`}
    >
      {/* Logo / Collapse Button */}
      <div className={`border-b border-slate-700/70 flex items-center ${isCollapsed ? 'justify-center py-3' : 'p-4 justify-between'}`}>
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
          onClick={toggleCollapsed}
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
      <nav className={`flex-1 space-y-0.5 ${isCollapsed ? 'p-1' : 'p-2'}`}>
        {dailyItems.map(renderNavItem)}
        {showSetup && (
          <>
            {!isCollapsed ? (
              <p className="text-[10px] uppercase tracking-wider text-slate-500 px-3 pt-4 pb-1">SETUP</p>
            ) : (
              <div className="border-t border-slate-700/70 mt-2 pt-2" />
            )}
            {setupItems.map(renderNavItem)}
          </>
        )}
      </nav>

      {/* User block + Logout */}
      <div className={`border-t border-slate-700/70 space-y-1 ${isCollapsed ? 'p-1' : 'p-2'}`}>
        {username && (
          <div className={`flex items-center gap-2.5 py-2 ${isCollapsed ? 'justify-center px-0' : 'px-2'}`}>
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
        {role === 'admin' && <ActsAsSwitch collapsed={isCollapsed} />}
        <NotificationBell collapsed={isCollapsed} />
        <button
          onClick={logout}
          className={`w-full py-2 rounded-md border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-300 hover:bg-red-500/10 font-medium text-sm ${isCollapsed ? 'px-0' : 'px-3'}`}
          title={isCollapsed ? 'Logout' : ''}
        >
          {isCollapsed ? '↪' : 'Logout'}
        </button>
      </div>
    </aside>
  );
}

/**
 * Sidebar - Main navigation component with collapse/expand.
 *
 * On a project page it starts as a 48 px icon rail so the items list and the
 * detail get the width; the choice made there is remembered per browser.
 * Everywhere else it starts expanded, as before, and is not remembered.
 */

import { useState, type ComponentType } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  BookOpen, ChartColumn, CircleDollarSign, Factory, FolderKanban, GitPullRequestArrow, GraduationCap,
  LayoutDashboard, ListChecks, LogOut, Palette, PanelLeftClose, PanelLeftOpen, Receipt, Settings2,
  ShoppingCart, Workflow, type LucideProps,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import SearchBox from '../SearchBox';
import NotificationBell from '../NotificationBell';
import { useOpenTaskCount } from '../../hooks/queries/useOpenTaskCount';
import { readStored, writeStored } from '../../lib/safeStorage';
import ActsAsSwitch from './ActsAsSwitch';

const RAIL_KEY = 'plm2.sidebar.projectRail';

interface NavItem {
  path: string;
  label: string;
  icon: ComponentType<LucideProps>;
}

function isProjectPage(path: string): boolean {
  return /^\/projects\/\d+(\/|$)/.test(path);
}

export default function Sidebar() {
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

  const dailyItems: NavItem[] = [
    { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/projects', label: 'Projects', icon: FolderKanban },
    { path: '/catalog', label: 'Purchased Parts', icon: ShoppingCart },
    { path: '/paints', label: 'Paints', icon: Palette },
    { path: '/suppliers', label: 'Suppliers', icon: Factory },
    { path: '/lessons', label: 'Lessons Learned', icon: BookOpen },
    { path: '/changes', label: 'Changes', icon: GitPullRequestArrow },
    { path: '/process-map', label: 'Process Flow', icon: Workflow },
    { path: '/pnl', label: 'P&L', icon: CircleDollarSign },
    { path: '/reports', label: 'Reports', icon: ChartColumn },
    { path: '/my-tasks', label: 'My Tasks', icon: ListChecks },
    { path: '/training', label: 'Training', icon: GraduationCap },
  ];

  const setupItems: NavItem[] = [
    { path: '/workflows', label: 'Workflows', icon: Settings2 },
    { path: '/cost-sheet', label: 'Cost sheet', icon: Receipt },
  ];

  const showSetup = role === 'admin' || role === 'engineer';

  // A detail page (/changes/21) keeps its section lit.
  const isActive = (path: string) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`);

  const renderNavItem = (item: NavItem) => {
    const active = isActive(item.path);
    const Icon = item.icon;
    const count = item.path === '/my-tasks' ? openTasks : 0;
    return (
      <Link
        key={item.path}
        to={item.path}
        aria-current={active ? 'page' : undefined}
        aria-label={isCollapsed ? (count > 0 ? `${item.label}, ${count} open` : item.label) : undefined}
        className={`group relative w-full py-2 rounded-md text-sm font-medium flex items-center gap-3 transition-colors ${
          isCollapsed ? 'justify-center px-0' : 'px-3'
        } ${
          active
            ? 'bg-sky-500/10 text-sky-300'
            : 'text-slate-400 hover:bg-slate-700/60 hover:text-slate-200'
        }`}
        title={isCollapsed ? item.label : undefined}
      >
        {active && (
          <span aria-hidden="true" className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-full bg-sky-400" />
        )}
        <Icon aria-hidden="true" size={18} strokeWidth={1.75}
          className={`flex-shrink-0 ${active ? 'text-sky-300' : 'text-slate-500 group-hover:text-slate-300'}`} />
        {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
        {count > 0 && (
          <span className={isCollapsed
            ? 'absolute top-0 right-0 min-w-[1rem] px-1 rounded bg-amber-500 text-slate-900 text-[11px] leading-4 font-bold text-center tabular-nums'
            : 'px-1.5 py-0.5 rounded-md bg-amber-500 text-slate-900 text-xs font-bold flex-shrink-0 tabular-nums'}>
            {count}
            {!isCollapsed && <span className="sr-only"> open</span>}
          </span>
        )}
      </Link>
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
          type="button"
          onClick={toggleCollapsed}
          className="p-1.5 hover:bg-slate-700 rounded-md text-slate-400 hover:text-slate-100"
          title={isCollapsed ? 'Expand' : 'Collapse'}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!isCollapsed}
        >
          {isCollapsed
            ? <PanelLeftOpen aria-hidden="true" size={18} strokeWidth={1.75} />
            : <PanelLeftClose aria-hidden="true" size={18} strokeWidth={1.75} />}
        </button>
      </div>

      {/* Search */}
      {!isCollapsed && (
        <div className="p-2 border-b border-slate-700/70">
          <SearchBox />
        </div>
      )}

      {/* Navigation Items */}
      <nav aria-label="Main" className={`flex-1 space-y-0.5 ${isCollapsed ? 'p-1' : 'p-2'}`}>
        {dailyItems.map(renderNavItem)}
        {showSetup && (
          <>
            {!isCollapsed ? (
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500 px-3 pt-4 pb-1">SETUP</p>
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
          type="button"
          onClick={logout}
          className={`w-full py-2 rounded-md text-slate-400 hover:text-slate-100 hover:bg-slate-700/60 font-medium text-sm flex items-center gap-3 ${isCollapsed ? 'justify-center px-0' : 'px-3'}`}
          title={isCollapsed ? 'Log out' : undefined}
          aria-label={isCollapsed ? 'Log out' : undefined}
        >
          <LogOut aria-hidden="true" size={18} strokeWidth={1.75} className="flex-shrink-0" />
          {!isCollapsed && <span>Log out</span>}
        </button>
      </div>
    </aside>
  );
}

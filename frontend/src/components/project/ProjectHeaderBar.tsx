/**
 * One-line project header: code, name and customer, and the project actions
 * menu. The SEP gates, changes and lessons live in the status nav bar below.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import { CUSTOMER_NAMING_LABELS, type Project } from './projectTypes';

export default function ProjectHeaderBar({ project, onStartChange, onAddPart }: {
  project: Project;
  onStartChange(): void;
  onAddPart(): void;
}) {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const customer = project.customer_naming ? CUSTOMER_NAMING_LABELS[project.customer_naming] : null;
  const menuItem = 'w-full text-left px-3 py-2 rounded text-sm text-slate-200 hover:bg-slate-700';

  return (
    <header
      data-testid="project-header"
      className="flex-shrink-0 h-12 px-4 flex items-center gap-3 border-b border-slate-700 bg-slate-900"
    >
      <button
        aria-label="Back to projects"
        title="Back to projects"
        onClick={() => navigate('/projects')}
        className="text-slate-400 hover:text-slate-200 text-sm"
      >
        ←
      </button>
      <h1 className="min-w-0 truncate text-sm text-slate-100">
        <span className="font-mono font-semibold">{project.code}</span>{' '}
        <span className="font-semibold">{project.name}</span>
        {customer && <span className="text-slate-400"> · {customer}</span>}
      </h1>
      <div className="ml-auto relative" ref={menuRef}>
        <button
          aria-label="Project actions"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
          className="px-2 py-1 rounded text-slate-300 hover:bg-slate-700 text-lg leading-none"
        >
          ⋯
        </button>
        {menuOpen && (
          <div role="menu" className="absolute right-0 top-full mt-1 z-40 w-80 rounded-lg border border-slate-700 bg-slate-800 shadow-lg p-2 space-y-1">
            <StartChangeButton
              label="Start change request"
              onClick={() => { setMenuOpen(false); onStartChange(); }}
              className={menuItem}
            />
            <button role="menuitem" onClick={() => { setMenuOpen(false); onAddPart(); }} className={menuItem}>
              + Add Part
            </button>
            <div className="px-3 py-2">
              <CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
            </div>
            <div className="px-3 pt-2 pb-1 border-t border-slate-700">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Timing gates</p>
              <MilestoneStrip projectId={project.id} />
            </div>
          </div>
        )}
      </div>
    </header>
  );
}

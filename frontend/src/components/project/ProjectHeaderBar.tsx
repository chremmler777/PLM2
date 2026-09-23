/**
 * One-line project header: code, name and customer, three status chips that
 * open their section in the slide-over, and the project actions menu.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { useProjectStatus, type ChipTone, type StatusChip } from '../../hooks/queries/useProjectStatus';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import { CUSTOMER_NAMING_LABELS, type Project } from './projectTypes';
import type { StatusSection } from './StatusSlideOver';

const TONE_CLASS: Record<ChipTone, string> = {
  neutral: 'border-slate-600 bg-slate-800 text-slate-200',
  green: 'border-emerald-700 bg-emerald-900/30 text-emerald-200',
  yellow: 'border-yellow-700 bg-yellow-900/30 text-yellow-200',
  red: 'border-red-700 bg-red-900/30 text-red-200',
  amber: 'border-amber-600 bg-amber-600/20 text-amber-300',
};

function Chip({ chip, testId, onClick }: { chip: StatusChip; testId: string; onClick(): void }) {
  return (
    <button
      type="button"
      data-testid={testId}
      title={chip.title}
      onClick={onClick}
      className={`px-2 py-0.5 rounded-full border text-xs font-medium whitespace-nowrap hover:brightness-125 ${TONE_CLASS[chip.tone]}`}
    >
      {chip.label}
    </button>
  );
}

export default function ProjectHeaderBar({ project, onOpenSection, onStartChange, onAddPart }: {
  project: Project;
  onOpenSection(section: StatusSection): void;
  onStartChange(): void;
  onAddPart(): void;
}) {
  const navigate = useNavigate();
  const status = useProjectStatus(project.id);
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
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <Chip chip={status.sep} testId="chip-sep" onClick={() => onOpenSection('sep')} />
        <Chip chip={status.changes} testId="chip-changes" onClick={() => onOpenSection('changes')} />
        <Chip chip={status.lessons} testId="chip-lessons" onClick={() => onOpenSection('lessons')} />
      </div>
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

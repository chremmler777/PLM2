/**
 * One-line project header: code, name and customer, and the project actions
 * menu. The SEP gates, changes and lessons live in the status nav bar below.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import { Users } from 'lucide-react';
import ProjectTeamDialog, { openSlots, useProjectTeam } from './ProjectTeamDialog';
import { ProjectMailListCard } from './ProjectMailListCard';
import { CUSTOMER_NAMING_LABELS, type Project } from './projectTypes';
import { t } from '../../i18n/cmLabels';

export default function ProjectHeaderBar({ project, onStartChange, onAddPart, back }: {
  project: Project;
  onStartChange(): void;
  onAddPart(): void;
  /** One level up inside the project (e.g. worksheet → items). Without it, ← leaves to the project list. */
  back?: { label: string; onClick(): void };
}) {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [teamOpen, setTeamOpen] = useState(false);
  // red dot: departments with members and no responsible (team not defined)
  const { data: team } = useProjectTeam(project.id);
  const gaps = openSlots(team);
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
        data-testid="project-back"
        aria-label={back ? `Back to ${back.label.toLowerCase()}` : 'Back to projects'}
        title={back ? `Back to ${back.label.toLowerCase()}` : 'Back to projects'}
        onClick={back ? back.onClick : () => navigate('/projects')}
        className="px-2 py-1 rounded text-slate-300 hover:text-slate-100 hover:bg-slate-700 text-sm whitespace-nowrap"
      >
        ← {back ? back.label : 'Projects'}
      </button>
      <h1 className="min-w-0 truncate text-sm text-slate-100">
        <span className="font-mono font-semibold">{project.code}</span>{' '}
        <span className="font-semibold">{project.name}</span>
        {customer && <span className="text-slate-400"> · {customer}</span>}
      </h1>
      <button
        type="button"
        data-testid="project-team-button"
        aria-label={gaps > 0 ? `${t('team.openFull')}, ${t('team.incompleteN').replace('{n}', String(gaps))}` : t('team.openFull')}
        title={gaps > 0 ? t('team.incompleteN').replace('{n}', String(gaps)) : t('team.openFull')}
        onClick={() => setTeamOpen(true)}
        className="ml-auto px-2 py-1 rounded text-slate-300 hover:text-slate-100 hover:bg-slate-700 text-sm whitespace-nowrap inline-flex items-center gap-1.5"
      >
        <Users aria-hidden="true" size={16} strokeWidth={1.75} />
        {t('team.open')}
        {gaps > 0 && (
          <span data-testid="project-team-gaps" aria-hidden="true"
            className="min-w-[1.1rem] rounded-full bg-red-600 px-1 text-center text-[11px] font-bold leading-4 text-white tabular-nums">
            {gaps}
          </span>
        )}
      </button>
      <ProjectTeamDialog projectId={project.id} projectLabel={`${project.code} ${project.name}`} open={teamOpen} onClose={() => setTeamOpen(false)} />
      <div className="relative" ref={menuRef}>
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
              block
            />
            <button role="menuitem" onClick={() => { setMenuOpen(false); onAddPart(); }} className={menuItem}>
              + Add Part
            </button>
            <div className="px-3 py-2">
              <CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
            </div>
            <button role="menuitem" data-testid="menu-project-team"
              onClick={() => { setMenuOpen(false); setTeamOpen(true); }} className={`${menuItem} flex items-center gap-2`}>
              <Users aria-hidden="true" size={14} className="text-slate-400" />{t('team.title')}…
            </button>
            <div className="px-3 pt-2 pb-2 border-t border-slate-700">
              <ProjectMailListCard projectId={project.id} />
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

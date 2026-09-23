/**
 * Project status nav bar under the one-line header. Left, the SEP Q-gate strip
 * in its collapsed form, always shown; right, Changes and Lessons. Each gate
 * chip and both buttons are nav items: clicking one opens its content inline
 * below the bar, closing whatever was open; clicking the active item again or
 * pressing Escape closes it. Nothing is remembered across reloads.
 */
import { useEffect, useId, useState } from 'react';
import ProjectSepSection from '../ProjectSepSection';
import ProjectChangesSection from '../ProjectChangesSection';
import ProjectLessonsSection from '../ProjectLessonsSection';
import { useProjectStatus, type ChipTone, type StatusChip } from '../../hooks/queries/useProjectStatus';

type OpenPanel = { kind: 'gate'; gateId: number } | { kind: 'changes' } | { kind: 'lessons' } | null;

const TONE_CLASS: Record<ChipTone, string> = {
  neutral: 'border-slate-600 bg-slate-800 text-slate-200 hover:border-slate-400',
  green: 'border-emerald-700 bg-emerald-900/30 text-emerald-200 hover:border-emerald-500',
  amber: 'border-amber-600 bg-amber-600/20 text-amber-300 hover:border-amber-400',
};
const ACTIVE_CLASS = 'ring-1 ring-blue-400 border-blue-400';

function NavButton({ chip, active, panelId, onClick }: {
  chip: StatusChip; active: boolean; panelId: string; onClick(): void;
}) {
  return (
    <button
      type="button"
      title={chip.title}
      aria-expanded={active}
      aria-controls={panelId}
      onClick={onClick}
      className={`px-2.5 py-1.5 rounded border text-xs font-medium whitespace-nowrap ${TONE_CLASS[chip.tone]} ${active ? ACTIVE_CLASS : ''}`}
    >
      {chip.label} {active ? '▾' : '▸'}
    </button>
  );
}

/** Escape belongs to a modal dialog or a field being edited, not to the panel. */
function escapeIsTaken(e: KeyboardEvent): boolean {
  if (e.defaultPrevented) return true;
  if (document.querySelector('[role="dialog"][aria-modal="true"]')) return true;
  const target = e.target;
  return target instanceof HTMLElement
    && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

export default function ProjectStatusNav({ projectId }: { projectId: number }) {
  const panelId = useId();
  const status = useProjectStatus(projectId);
  const [open, setOpen] = useState<OpenPanel>(null);

  const isOpen = open !== null;
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !escapeIsTaken(e)) setOpen(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen]);

  const toggleGate = (gateId: number) =>
    setOpen((o) => (o?.kind === 'gate' && o.gateId === gateId ? null : { kind: 'gate', gateId }));
  const toggle = (kind: 'changes' | 'lessons') =>
    setOpen((o) => (o?.kind === kind ? null : { kind }));

  return (
    <>
      <nav
        data-testid="project-status-nav"
        aria-label="Project status"
        className="flex-shrink-0 px-4 py-2 flex items-center gap-x-4 gap-y-2 flex-wrap border-b border-slate-700 bg-slate-800/60"
      >
        <div className="min-w-0 flex-1">
          <ProjectSepSection
            projectId={projectId}
            view="strip"
            gateId={open?.kind === 'gate' ? open.gateId : null}
            onGateClick={toggleGate}
            panelId={panelId}
          />
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0 ml-auto">
          <NavButton chip={status.changes} active={open?.kind === 'changes'} panelId={panelId} onClick={() => toggle('changes')} />
          <NavButton chip={status.lessons} active={open?.kind === 'lessons'} panelId={panelId} onClick={() => toggle('lessons')} />
        </div>
      </nav>
      <section
        id={panelId}
        data-testid="status-panel"
        aria-label="Project status details"
        hidden={!isOpen}
        className="flex-shrink-0 max-h-[45vh] overflow-y-auto border-b border-slate-700 bg-slate-800 px-4 py-3 [&>div]:mb-0"
      >
        {open?.kind === 'gate' && <ProjectSepSection projectId={projectId} view="gate" gateId={open.gateId} />}
        {open?.kind === 'changes' && <ProjectChangesSection projectId={projectId} />}
        {open?.kind === 'lessons' && <ProjectLessonsSection projectId={projectId} />}
      </section>
    </>
  );
}

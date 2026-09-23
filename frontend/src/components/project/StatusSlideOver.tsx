/**
 * Slide-over from the right that hosts one of the project status sections
 * (SEP Q-gates, changes, lessons) unchanged. Escape or a click outside closes it.
 * Focus moves to its close button on open and back to the opening chip on close.
 */
import { useEffect, useRef } from 'react';
import ProjectSepSection from '../ProjectSepSection';
import ProjectChangesSection from '../ProjectChangesSection';
import ProjectLessonsSection from '../ProjectLessonsSection';

export type StatusSection = 'sep' | 'changes' | 'lessons';

const TITLES: Record<StatusSection, string> = {
  sep: 'SEP Q-Gates',
  changes: 'Changes',
  lessons: 'Lessons',
};

export default function StatusSlideOver({ section, projectId, onClose }: {
  section: StatusSection | null;
  projectId: number;
  onClose(): void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!section) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      // A dialog opened by the section (inline or portaled) owns its Escape.
      const active = document.activeElement;
      const dialog = active instanceof Element ? active.closest('[role="dialog"]') : null;
      if (dialog && dialog !== panelRef.current) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [section, onClose]);

  // Keyed on open/closed only: switching sections keeps focus where it is.
  const open = section !== null;
  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    return () => {
      if (trigger?.isConnected) trigger.focus();
    };
  }, [open]);

  if (!section) return null;

  return (
    <div className="fixed inset-0 z-30" data-testid="status-slideover">
      <div data-testid="slideover-backdrop" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={TITLES[section]}
        className="absolute right-0 top-0 h-full w-full max-w-2xl bg-slate-900 border-l border-slate-700 shadow-xl flex flex-col"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 flex-shrink-0">
          <h2 className="text-sm font-semibold text-slate-200">{TITLES[section]}</h2>
          <button ref={closeRef} aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg leading-none">×</button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {section === 'sep' && <ProjectSepSection projectId={projectId} />}
          {section === 'changes' && <ProjectChangesSection projectId={projectId} />}
          {section === 'lessons' && <ProjectLessonsSection projectId={projectId} />}
        </div>
      </aside>
    </div>
  );
}

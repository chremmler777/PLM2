import { useId, useState, type ReactNode } from 'react';
import { CircleHelp } from 'lucide-react';

/**
 * A "?" next to a field that opens a short explanation right below it
 * (Christoph 2026-10-27, first on Start change → Urgent). Click toggles,
 * Escape closes the panel only, not the dialog around it.
 */
export default function InfoButton({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}
        onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); setOpen(false); } }}
        className="inline-flex items-center justify-center rounded-full p-0.5 text-slate-400 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
      >
        <CircleHelp className="h-4 w-4" aria-hidden="true" />
      </button>
      {open && (
        <div
          id={panelId}
          role="note"
          className="basis-full mt-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs leading-relaxed text-slate-300"
        >
          {children}
        </div>
      )}
    </>
  );
}

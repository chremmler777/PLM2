/**
 * RevisionStrip - majors as tabs (E1 · 003, E2 · 004, 1), each with its
 * proposals nested under it (E1.1). Replaces the flat revision dropdown so a
 * proposal is visible as a proposal. E numbers are our filing order; the
 * customer index is shown next to them.
 */
import { groupByMajor } from './revisionGrouping';
import { revisionLabel } from './RevisionBadge';

export interface StripRevision {
  id: number;
  revision_name: string;
  customer_index?: string | null;
  status: string;
  phase: 'review' | 'official';
  parent_revision_id?: number | null;
}

interface Props {
  revisions: StripRevision[];
  selectedId: number | null;
  activeId: number | null;
  onSelect(id: number): void;
  onNewProposal?(majorId: number): void;
}

const DEAD = new Set(['rejected', 'cancelled', 'archived']);

function tabClass(rev: StripRevision, selected: boolean, minor: boolean): string {
  const base = minor ? 'px-2 py-0.5 text-xs rounded' : 'px-3 py-1 text-sm rounded-t border-b-2';
  const tone = selected
    ? 'bg-slate-700 text-white border-blue-500'
    : 'text-slate-300 hover:bg-slate-700/60 border-transparent';
  const state = DEAD.has(rev.status) ? 'line-through opacity-60' : rev.status === 'frozen' ? 'opacity-70' : '';
  return `${base} ${tone} ${state}`;
}

export default function RevisionStrip({ revisions, selectedId, activeId, onSelect, onNewProposal }: Props) {
  if (revisions.length === 0) return <p className="text-xs text-slate-500 px-2 py-1">No revisions yet</p>;
  const groups = groupByMajor(revisions);
  return (
    <div className="flex flex-wrap items-end gap-3 px-2 py-1" role="tablist">
      {groups.map(({ major, minors }) => {
        const majorSelected = selectedId === major.id;
        return (
          <div key={major.id} data-testid={`rev-group-${major.id}`} className="flex flex-col gap-1">
            <button role="tab" aria-selected={majorSelected} data-testid={`rev-tab-${major.id}`}
              onClick={() => onSelect(major.id)} className={tabClass(major as StripRevision, majorSelected, false)}>
              {revisionLabel(major.revision_name, major.customer_index)}
              {activeId === major.id && <span className="ml-1 text-[10px] uppercase text-green-400">active</span>}
              <span className="ml-1 text-[10px] text-slate-500">{major.status.replace(/_/g, ' ')}</span>
            </button>
            {(minors.length > 0 || (onNewProposal && majorSelected)) && (
              <div className="flex items-center gap-1 pl-2">
                {minors.map((m) => (
                  <button key={m.id} role="tab" aria-selected={selectedId === m.id} data-testid={`rev-tab-${m.id}`}
                    onClick={() => onSelect(m.id)} className={tabClass(m as StripRevision, selectedId === m.id, true)}>
                    {m.revision_name}
                    <span className="ml-1 text-[10px] text-amber-300">proposal</span>
                    <span className="ml-1 text-[10px] text-slate-500">{m.status.replace(/_/g, ' ')}</span>
                  </button>
                ))}
                {onNewProposal && majorSelected && (
                  <button onClick={() => onNewProposal(major.id)}
                    className="px-2 py-0.5 text-xs rounded border border-dashed border-slate-600 text-slate-400 hover:text-white hover:border-slate-400">
                    + Proposal
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

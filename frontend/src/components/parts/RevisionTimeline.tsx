/**
 * Revision timeline: one card per customer major (E1, E2, 1, 2 …) with our
 * internal proposals (E1.1, 1.1 …) nested underneath.
 */
import { groupByMajor, type Revision } from './revisionGrouping';

export type { Revision } from './revisionGrouping';

const statusColor: Record<string, string> = {
  draft: 'bg-slate-700 text-slate-200',
  approved: 'bg-emerald-900/40 text-emerald-300',
  rejected: 'bg-red-900/40 text-red-300',
  archived: 'bg-slate-800 text-slate-400',
  frozen: 'bg-sky-900/40 text-sky-300',
};

function Badge({ children, tone = 'bg-slate-700 text-slate-200' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`text-xs px-2 py-0.5 rounded-full ${tone}`}>{children}</span>;
}

interface Props {
  revisions: Revision[];
  activeRevisionId?: number | null;
  onNewProposal(parentId: number): void;
  onPromote(rev: Revision): void;
  onReject(id: number): void;
  onUnreject(id: number): void;
}

export default function RevisionTimeline({ revisions, activeRevisionId, onNewProposal, onPromote, onReject, onUnreject }: Props) {
  const groups = groupByMajor(revisions);
  if (groups.length === 0) {
    return <p className="text-slate-400 text-center py-8">No customer data yet.</p>;
  }
  return (
    <div className="space-y-4">
      {groups.map(({ major, minors }) => (
        <div key={major.id} data-testid={`major-${major.revision_name}`}
          className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-lg font-bold text-slate-100">{major.revision_name}</span>
                <Badge tone={major.phase === 'official' ? 'bg-amber-900/40 text-amber-300' : 'bg-blue-900/40 text-blue-300'}>
                  {major.phase}
                </Badge>
                <Badge>{major.part_phase_at_receipt}</Badge>
                {major.customer_index && <Badge>index {major.customer_index}</Badge>}
                {activeRevisionId === major.id && <Badge tone="bg-emerald-900/40 text-emerald-300">active</Badge>}
                <Badge tone={statusColor[major.status] ?? ''}>{major.status}</Badge>
              </div>
              {major.summary && <p className="text-sm text-slate-300">{major.summary}</p>}
              <p className="text-xs text-slate-500">
                {major.customer_received_at ? `Received ${major.customer_received_at}` : `Created ${new Date(major.created_at).toLocaleDateString()}`}
              </p>
            </div>
            <button data-testid={`new-proposal-${major.id}`} onClick={() => onNewProposal(major.id)}
              className="px-3 py-1 text-sm rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
              + Proposal
            </button>
          </div>

          {minors.length > 0 && (
            <div className="mt-3 space-y-2 border-l-2 border-slate-700 pl-4">
              {minors.map((m) => (
                <div key={m.id} data-testid={`minor-${m.revision_name}`} className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-slate-100">{m.revision_name}</span>
                      <Badge tone={statusColor[m.status] ?? ''}>{m.status}</Badge>
                    </div>
                    {m.summary && <p className="text-sm text-slate-300">{m.summary}</p>}
                  </div>
                  <div className="flex gap-2">
                    {m.status === 'draft' && (
                      <button data-testid={`promote-${m.id}`} onClick={() => onPromote(m)}
                        className="px-3 py-1 text-sm rounded bg-purple-900/40 text-purple-200 hover:bg-purple-900/60">
                        Customer adopted
                      </button>
                    )}
                    {m.status !== 'rejected' && m.status !== 'archived' && m.status !== 'approved' && (
                      <button onClick={() => onReject(m.id)}
                        className="px-3 py-1 text-sm rounded bg-red-900/40 text-red-200 hover:bg-red-900/60">Reject</button>
                    )}
                    {(m.status === 'rejected' || m.status === 'archived') && (
                      <button onClick={() => onUnreject(m.id)}
                        className="px-3 py-1 text-sm rounded bg-yellow-900/40 text-yellow-200 hover:bg-yellow-900/60">Restore</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

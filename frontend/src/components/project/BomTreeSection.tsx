/** Multi-level BOM of the selected revision, plus where the part is used. */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import BomTree, { type BomNode } from '../parts/BomTree';
import { revisionLabel } from '../parts/RevisionBadge';

interface WhereUsedEntry {
  part_id: number;
  part_number: string;
  revision_name: string;
  customer_index?: string | null;
  parents: WhereUsedEntry[];
}

function flattenUsedIn(list: WhereUsedEntry[], acc: WhereUsedEntry[] = []): WhereUsedEntry[] {
  for (const u of list) {
    if (!acc.some((a) => a.part_id === u.part_id)) acc.push(u);
    flattenUsedIn(u.parents, acc);
  }
  return acc;
}

export function BomTreeSection({ partId, revisionId, revisionName, onOpenPart }: {
  partId: number; revisionId: number; revisionName?: string; onOpenPart(id: number): void;
}) {
  const { data: tree } = useQuery({
    queryKey: ['bom-tree', partId, revisionId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/bom-tree`, { params: { revision_id: revisionId } })).data as BomNode,
  });
  const { data: usedIn } = useQuery({
    queryKey: ['where-used', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/where-used`)).data as WhereUsedEntry[],
  });
  const parents = usedIn ? flattenUsedIn(usedIn) : [];
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4 mb-4" data-testid="bom-tree-section">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3 className="font-semibold text-slate-100">
          Bill of materials{revisionName ? <span className="text-slate-400 font-normal"> · {revisionName}</span> : null}
        </h3>
        {parents.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap text-xs">
            <span className="text-slate-400 mr-1">Used in</span>
            {parents.map((u) => (
              <button key={u.part_id} onClick={() => onOpenPart(u.part_id)}
                className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600 font-mono">
                {u.part_number} <span className="text-slate-400 font-sans">{revisionLabel(u.revision_name, u.customer_index)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {tree ? <BomTree tree={tree} onOpenPart={onOpenPart} /> : <p className="text-slate-400 text-sm">Loading…</p>}
    </div>
  );
}

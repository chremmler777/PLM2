/**
 * AssemblyTreeList - the "Assemblies" view of a project: top-level
 * assemblies (BOM lines, used nowhere) that expand into their BOM tree.
 * Driven by the revision BOM only, never by the drag-and-drop parent link.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import type { BomNode, BomLine } from './BomTree';

export interface AssemblyRoot {
  part_id: number;
  part_number: string;
  name: string;
  part_type: string;
  item_category: string;
  revision_id: number;
  revision_name: string;
  revision_phase: 'review' | 'official';
  line_count: number;
}

interface Props {
  projectId: number;
  selectedPartId: number | null;
  onSelect(partId: number): void;
}

function RevBadge({ name, phase }: { name: string | null; phase: string | null }) {
  if (!name) return <span className="text-xs text-slate-500">no data</span>;
  return (
    <span className={`text-xs px-1.5 rounded ${phase === 'official' ? 'bg-amber-900/40 text-amber-300' : 'bg-blue-900/40 text-blue-300'}`}>
      {name}
    </span>
  );
}

function NodeRow({ node, qty, unit, depth, selectedPartId, onSelect }: {
  node: BomNode; qty?: number; unit?: string; depth: number; selectedPartId: number | null; onSelect(id: number): void;
}) {
  const [open, setOpen] = useState(depth === 0);
  const expandable = node.lines.length > 0 && !node.cycle;
  return (
    <>
      <div data-testid={`asm-node-${node.part_id}`}
        className={`flex items-center gap-1.5 py-1 pr-2 rounded text-sm cursor-pointer ${selectedPartId === node.part_id ? 'bg-blue-900/40' : 'hover:bg-slate-700/50'}`}
        style={{ paddingLeft: `${depth * 1}rem` }}
        onClick={() => onSelect(node.part_id)}>
        {expandable ? (
          <button data-testid={`asm-toggle-${node.part_id}`} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
            className="w-4 text-slate-400 hover:text-slate-100">{open ? '▾' : '▸'}</button>
        ) : <span className="w-4" />}
        <span className="font-mono text-slate-100 truncate">{node.part_number}</span>
        <span className="text-slate-400 truncate flex-1">{node.name}</span>
        {qty !== undefined && <span className="text-xs text-slate-400 tabular-nums">{qty} {unit}</span>}
        <RevBadge name={node.revision_name} phase={node.revision_phase} />
        {node.part_type === 'purchased' && <span className="text-xs text-slate-500">buy</span>}
      </div>
      {open && expandable && node.lines.map((l: BomLine) => l.child ? (
        <NodeRow key={l.id} node={l.child} qty={l.quantity} unit={l.unit} depth={depth + 1}
          selectedPartId={selectedPartId} onSelect={onSelect} />
      ) : (
        <div key={l.id} className="flex items-center gap-1.5 py-1 text-sm text-slate-400" style={{ paddingLeft: `${(depth + 1) * 1 + 1.4}rem` }}>
          <span className="truncate flex-1">{l.name}</span>
          <span className="text-xs tabular-nums">{l.quantity} {l.unit}</span>
        </div>
      ))}
    </>
  );
}

function AssemblyRootRow({ root, selectedPartId, onSelect }: { root: AssemblyRoot; selectedPartId: number | null; onSelect(id: number): void }) {
  const [open, setOpen] = useState(false);
  const { data: tree } = useQuery({
    queryKey: ['bom-tree', root.part_id, root.revision_id],
    queryFn: async () => (await client.get(`/v1/parts/${root.part_id}/bom-tree`, { params: { revision_id: root.revision_id } })).data as BomNode,
    enabled: open,
  });
  return (
    <div className="border border-slate-700 rounded-lg p-1 bg-slate-800/60">
      <div data-testid={`asm-root-${root.part_id}`}
        className={`flex items-center gap-1.5 py-1 px-1 rounded text-sm cursor-pointer ${selectedPartId === root.part_id ? 'bg-blue-900/40' : 'hover:bg-slate-700/50'}`}
        onClick={() => onSelect(root.part_id)}>
        <button data-testid={`asm-root-toggle-${root.part_id}`} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
          className="w-4 text-slate-400 hover:text-slate-100">{open ? '▾' : '▸'}</button>
        <span className="font-mono text-slate-100 truncate">{root.part_number}</span>
        <span className="text-slate-400 truncate flex-1">{root.name}</span>
        <span className="text-xs text-slate-500">{root.line_count} lines</span>
        <RevBadge name={root.revision_name} phase={root.revision_phase} />
      </div>
      {open && (tree ? tree.lines.map((l) => l.child ? (
        <NodeRow key={l.id} node={l.child} qty={l.quantity} unit={l.unit} depth={1} selectedPartId={selectedPartId} onSelect={onSelect} />
      ) : (
        <div key={l.id} className="flex items-center gap-1.5 py-1 text-sm text-slate-400" style={{ paddingLeft: '2.4rem' }}>
          <span className="truncate flex-1">{l.name}</span>
          <span className="text-xs tabular-nums">{l.quantity} {l.unit}</span>
        </div>
      )) : <p className="text-xs text-slate-500 pl-6 py-1">Loading…</p>)}
    </div>
  );
}

export default function AssemblyTreeList({ projectId, selectedPartId, onSelect }: Props) {
  const { data: roots, isLoading } = useQuery({
    queryKey: ['project-assemblies', projectId],
    queryFn: async () => (await client.get(`/v1/parts/project/${projectId}/assemblies`)).data as AssemblyRoot[],
  });
  if (isLoading) return <p className="text-slate-500 text-sm">Loading...</p>;
  if (!roots || roots.length === 0) {
    return <p className="text-slate-500 text-sm">No assemblies yet. Add BOM lines to a part and it shows up here.</p>;
  }
  return (
    <div className="space-y-1">
      {roots.map((r) => <AssemblyRootRow key={r.part_id} root={r} selectedPartId={selectedPartId} onSelect={onSelect} />)}
    </div>
  );
}

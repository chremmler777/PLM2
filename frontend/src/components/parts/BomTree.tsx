/**
 * BomTree - multi-level explosion of a part's BOM. Each child resolves to
 * its active revision; quantities multiply through to the leaves.
 */
import { useState } from 'react';
import RevisionBadge, { revisionLabel } from './RevisionBadge';

export interface BomNode {
  part_id: number;
  part_number: string;
  name: string;
  part_type: string;
  item_category: string;
  revision_id: number | null;
  revision_name: string | null;
  revision_phase: 'review' | 'official' | null;
  customer_index?: string | null;
  cycle: boolean;
  lines: BomLine[];
}

export interface BomLine {
  id: number;
  item_number: string;
  name: string;
  quantity: number;
  unit: string;
  total_quantity: number;
  child_part_id: number | null;
  catalog_part_id: number | null;
  child: BomNode | null;
}

function fmt(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '');
}

function Line({ line, depth, onOpenPart }: { line: BomLine; depth: number; onOpenPart?(id: number): void }) {
  const [open, setOpen] = useState(depth < 1);
  const child = line.child;
  const expandable = !!child && child.lines.length > 0;
  return (
    <>
      <div data-testid={`bom-line-${line.id}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 py-1.5 border-b border-slate-800 text-sm"
        style={{ paddingLeft: `${depth * 1.25}rem` }}>
        <div className="flex items-center gap-2 min-w-0">
          {expandable ? (
            <button data-testid={`bom-toggle-${line.id}`} onClick={() => setOpen(!open)}
              className="w-5 text-slate-400 hover:text-slate-100">{open ? '▾' : '▸'}</button>
          ) : <span className="w-5" />}
          <span className="text-xs text-slate-500 w-6">{line.item_number}</span>
          {child ? (
            <button onClick={() => onOpenPart?.(child.part_id)} className="font-mono text-slate-100 hover:underline truncate">
              {child.part_number}
            </button>
          ) : (
            <span className="text-slate-200 truncate">{line.name}</span>
          )}
          {child && <span className="text-slate-400 truncate">{child.name}</span>}
          {child && (
            <RevisionBadge testId={`bom-rev-${line.id}`} name={child.revision_name} index={child.customer_index} phase={child.revision_phase} />
          )}
          {child?.part_type === 'purchased' && <span className="text-xs px-1.5 rounded bg-slate-700 text-slate-300">purchased</span>}
          {child?.cycle && <span className="text-xs px-1.5 rounded bg-red-900/40 text-red-300">cycle</span>}
        </div>
        <span className="text-slate-300 tabular-nums">{fmt(line.quantity)} {line.unit}</span>
        <span data-testid={`bom-total-${line.id}`} className="text-slate-500 tabular-nums text-xs w-20 text-right">
          {line.total_quantity !== line.quantity ? `Σ ${fmt(line.total_quantity)}` : ''}
        </span>
      </div>
      {open && expandable && child!.lines.map((l) => <Line key={l.id} line={l} depth={depth + 1} onOpenPart={onOpenPart} />)}
    </>
  );
}

export default function BomTree({ tree, onOpenPart }: { tree: BomNode; onOpenPart?(id: number): void }) {
  if (tree.lines.length === 0) {
    return <p className="text-slate-400 text-sm">No BOM lines on {tree.revision_name ? revisionLabel(tree.revision_name, tree.customer_index) : 'this part'}.</p>;
  }
  return (
    <div>
      <div className="grid grid-cols-[1fr_auto_auto] gap-3 text-xs text-slate-500 pb-1 border-b border-slate-700">
        <span>Component</span><span>Qty</span><span className="w-20 text-right">Total</span>
      </div>
      {tree.lines.map((l) => <Line key={l.id} line={l} depth={0} onOpenPart={onOpenPart} />)}
    </div>
  );
}

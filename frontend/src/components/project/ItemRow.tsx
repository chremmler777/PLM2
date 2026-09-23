/** One item row of the project list, its expand block and its nested children. */
import { useState } from 'react';
import ColourSwatch from '../paint/ColourSwatch';
import { revisionLabel } from '../parts/RevisionBadge';
import { stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import { CATEGORY_META, typeColor, type TreeNode } from './projectTypes';

export default function ItemRow({
  node,
  selectedPartId,
  onSelect,
  onContextMenu,
  depth = 0,
  draggingPartId,
  invalidDropIds,
  onDragStartPart,
  onDragEndPart,
  onDropOnPart,
  projectCode,
  paintByPartId,
  structure,
  onSelectRevision,
}: {
  node: TreeNode;
  selectedPartId: number | null;
  onSelect: (id: number) => void;
  projectCode?: string;
  paintByPartId?: Map<number, PartPaintLayer>;
  onContextMenu: (e: React.MouseEvent, id: number) => void;
  depth?: number;
  draggingPartId: number | null;
  invalidDropIds: Set<number>;
  onDragStartPart: (id: number) => void;
  onDragEndPart: () => void;
  onDropOnPart: (targetId: number) => void;
  structure?: ProjectStructure;
  onSelectRevision?: (partId: number, revisionId: number) => void;
}) {
  const article = articleOf(structure, node.part.id);
  const hasChildren = node.children.length > 0;
  const hasStructure = !!article && (article.revisions.length > 0 || article.related.length > 0);
  const expandable = hasChildren || hasStructure;
  const [expanded, setExpanded] = useState(hasChildren);
  const [dragOver, setDragOver] = useState(false);
  const isRoot = depth === 0;
  const isHeadline = isRoot || hasChildren;

  const isDropTarget =
    draggingPartId !== null &&
    draggingPartId !== node.part.id &&
    node.part.part_type === 'sub_assembly' &&
    !invalidDropIds.has(node.part.id);

  return (
    <div>
      <button
        onClick={() => onSelect(node.part.id)}
        onContextMenu={(e) => onContextMenu(e, node.part.id)}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = 'move';
          onDragStartPart(node.part.id);
        }}
        onDragEnd={onDragEndPart}
        onDragOver={(e) => {
          if (isDropTarget) {
            e.preventDefault();
            setDragOver(true);
          }
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (isDropTarget) onDropOnPart(node.part.id);
        }}
        className={`text-left px-2 rounded border transition flex items-center gap-2 ${
          dragOver && isDropTarget
            ? 'bg-green-900/40 border-green-500'
            : selectedPartId === node.part.id
              ? 'bg-blue-900/40 border-blue-500'
              : isHeadline
                ? 'border-slate-600 bg-slate-700/40 hover:bg-slate-700/60'
                : 'border-slate-700 bg-slate-800/30 hover:bg-slate-800/50'
        } ${isHeadline ? 'py-2.5' : 'py-2'} ${draggingPartId === node.part.id ? 'opacity-40' : ''}`}
        style={{ marginLeft: `${depth * 20}px`, width: `calc(100% - ${depth * 20}px)` }}
      >
        {expandable ? (
          <button
            aria-label={expanded ? 'Collapse' : 'Expand'}
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="text-slate-400 hover:text-slate-200 text-xs w-4 h-4 flex items-center justify-center flex-shrink-0"
          >
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4 flex-shrink-0"></span>
        )}

        <div className={`truncate flex-1 min-w-0 ${isHeadline ? 'text-slate-50 text-sm font-bold' : 'text-slate-100 text-sm font-medium'}`}>
          <span className="text-slate-400 text-xs">{node.part.part_number}</span>
          <span className="mx-1">•</span>
          <span>{stripProjectCode(node.part.name, projectCode)}</span>
          {hasChildren && (
            <span className="ml-2 text-xs text-slate-500">
              ({node.children.length})
            </span>
          )}
          {article?.mirror_of && <span data-testid={`tree-mirror-of-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirror of {article.mirror_of.part_number}</span>}
          {article && article.mirrored_by.length > 0 && <span data-testid={`tree-mirrored-by-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirrored by {article.mirrored_by.map((m) => m.part_number).join(', ')}</span>}
        </div>
        {paintByPartId?.get(node.part.id) && (
          <span data-testid={`paint-swatch-${node.part.id}`} className="flex-shrink-0 flex items-center">
            <ColourSwatch
              hex={paintByPartId.get(node.part.id)!.paint.colour_hex}
              code={paintByPartId.get(node.part.id)!.paint.colour_code}
            />
          </span>
        )}
        {node.part.part_type === 'sub_assembly' && <span className="text-yellow-400 text-sm flex-shrink-0">★</span>}
        {node.part.item_category !== 'article' && CATEGORY_META[node.part.item_category] && (
          <span
            className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${CATEGORY_META[node.part.item_category].badge}`}
            title={CATEGORY_META[node.part.item_category].label}
          >
            {CATEGORY_META[node.part.item_category].icon}
          </span>
        )}
        <span className={`px-2 py-0.5 rounded text-xs font-medium flex-shrink-0 ${typeColor(node.part.part_type)}`}>
          {node.part.part_type.replace(/_/g, ' ')}
        </span>
      </button>

      {expanded && hasStructure && (
        // This block sits as a sibling of the row <button>, not nested inside it, so the
        // stopPropagation() calls on the chip buttons below are currently inert, kept as a
        // defensive guard in case this ever moves inside the row.
        <div className="ml-6 my-1 space-y-1 text-xs" style={{ marginLeft: `${depth * 20 + 24}px` }}>
          {(node.part.customer_part_number || node.part.tier1_part_number) && (
            <div className="flex flex-wrap items-center gap-1" data-testid={`tree-numbers-${node.part.id}`}>
              <span className="text-slate-500 w-16">Numbers</span>
              {node.part.customer_part_number && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono" title="Customer (OEM) part number">{node.part.customer_part_number}</span>
              )}
              {node.part.tier1_part_number && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono" title="Tier 1 part number">Tier 1 {node.part.tier1_part_number}</span>
              )}
            </div>
          )}
          {article!.revisions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Revisions</span>
              {article!.revisions.map((r) => (
                <button key={r.id} data-testid={`tree-rev-${r.id}`} onClick={(e) => { e.stopPropagation(); onSelectRevision?.(node.part.id, r.id); }}
                  className={`px-1.5 py-0.5 rounded ${r.parent_revision_id ? 'bg-amber-900/40 text-amber-200' : 'bg-slate-700 text-slate-200'} ${r.is_active ? 'font-semibold' : ''}`}>
                  {revisionLabel(r.revision_name, r.customer_index)}{r.parent_revision_id ? ' proposal' : ''}{r.is_active ? ' ●' : ''}
                </button>
              ))}
            </div>
          )}
          {article!.related.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Linked</span>
              {article!.related.map((r) => (
                <button key={`${r.relation_type}-${r.part_id}`} data-testid={`tree-rel-${r.part_id}`} onClick={(e) => { e.stopPropagation(); onSelect(r.part_id); }}
                  className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                  {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, projectCode)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <ItemRow
              key={child.part.id}
              node={child}
              selectedPartId={selectedPartId}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              depth={depth + 1}
              draggingPartId={draggingPartId}
              invalidDropIds={invalidDropIds}
              onDragStartPart={onDragStartPart}
              onDragEndPart={onDragEndPart}
              onDropOnPart={onDropOnPart}
              projectCode={projectCode}
              paintByPartId={paintByPartId}
              structure={structure}
              onSelectRevision={onSelectRevision}
            />
          ))}
        </div>
      )}
    </div>
  );
}

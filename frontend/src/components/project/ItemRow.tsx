/**
 * One item row: thumbnail, then short name with the active revision (our E
 * level bold) and phase on line 1, and the labelled KTX / Tier 1 / OEM
 * numbers with the mirror / paint / proposal marks on line 2. The expand
 * block (revisions, linked items) and drag-to-restructure onto a
 * sub-assembly work as before.
 */
import { useState } from 'react';
import ColourSwatch from '../paint/ColourSwatch';
import PartNumbers from '../parts/PartNumbers';
import PartThumbnail from '../parts/PartThumbnail';
import RevisionLabel from '../parts/RevisionLabel';
import { shortName, stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import { CATEGORY_META, type TreeNode } from './projectTypes';

export interface ItemRowProps {
  node: TreeNode;
  depth?: number;
  projectCode?: string;
  structure?: ProjectStructure;
  paintByPartId?: Map<number, PartPaintLayer>;
  selectedPartId: number | null;
  isExpanded(node: TreeNode): boolean;
  onSetExpanded(partId: number, next: boolean): void;
  onSelect(id: number): void;
  onContextMenu(e: React.MouseEvent, id: number): void;
  onSelectRevision?(partId: number, revisionId: number): void;
  draggingPartId: number | null;
  invalidDropIds: Set<number>;
  onDragStartPart(id: number): void;
  onDragEndPart(): void;
  onDropOnPart(targetId: number): void;
}

export default function ItemRow(props: ItemRowProps) {
  const {
    node, depth = 0, projectCode, structure, paintByPartId, selectedPartId, isExpanded, onSetExpanded,
    onSelect, onContextMenu, onSelectRevision, draggingPartId, invalidDropIds,
    onDragStartPart, onDragEndPart, onDropOnPart,
  } = props;
  const [dragOver, setDragOver] = useState(false);
  const part = node.part;
  const article = articleOf(structure, part.id);
  const hasChildren = node.children.length > 0;
  const hasStructure = !!article && (article.revisions.length > 0 || article.related.length > 0);
  const expandable = hasChildren || hasStructure;
  const expanded = expandable && isExpanded(node);
  const selected = selectedPartId === part.id;
  const isDropTarget =
    draggingPartId !== null &&
    draggingPartId !== part.id &&
    part.part_type === 'sub_assembly' &&
    !invalidDropIds.has(part.id);

  const customerNumber = part.customer_part_number ?? article?.customer_part_number ?? null;
  const activeRevision = article?.revisions.find((r) => r.is_active);
  const hasProposal = !!article?.revisions.some((r) => r.parent_revision_id !== null);
  const phase = article?.lifecycle_phase ?? part.lifecycle_phase;
  const paint = paintByPartId?.get(part.id);
  const thumbnailUrl = part.thumbnail_url ?? article?.thumbnail_url ?? null;
  const name = shortName(part.name, projectCode, customerNumber);
  const indent = depth * 16;

  return (
    <div>
      <div className="flex items-stretch gap-1" style={{ paddingLeft: `${indent}px` }}>
        {expandable ? (
          <button
            type="button"
            aria-label={expanded ? 'Collapse' : 'Expand'}
            onClick={() => onSetExpanded(part.id, !expanded)}
            className="w-4 flex-shrink-0 text-[10px] text-slate-500 hover:text-slate-200"
          >
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}
        <button
          type="button"
          data-testid={`item-row-${part.id}`}
          data-row-id={part.id}
          aria-current={selected ? 'true' : undefined}
          onClick={() => onSelect(part.id)}
          onContextMenu={(e) => onContextMenu(e, part.id)}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move';
            onDragStartPart(part.id);
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
            if (isDropTarget) onDropOnPart(part.id);
          }}
          className={`flex-1 min-w-0 text-left px-2 py-1 rounded border transition ${
            dragOver && isDropTarget
              ? 'bg-green-900/40 border-green-500'
              : selected
                ? 'bg-blue-900/40 border-blue-500'
                : 'border-transparent hover:bg-slate-800'
          } ${draggingPartId === part.id ? 'opacity-40' : ''}`}
        >
          <div className="flex items-center gap-2 min-w-0">
            <PartThumbnail url={thumbnailUrl} name={name} testId={`row-thumb-${part.id}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 min-w-0 text-sm">
                <span className="truncate text-slate-100">{name}</span>
                {part.part_type === 'sub_assembly' && <span className="text-yellow-400 flex-shrink-0" title="Sub-assembly">★</span>}
                {hasChildren && <span className="text-xs text-slate-500 flex-shrink-0">({node.children.length})</span>}
                <span className="ml-auto flex-shrink-0 flex items-center gap-1 text-[11px] text-slate-400">
                  {activeRevision && (
                    <RevisionLabel testId={`row-rev-${part.id}`} name={activeRevision.revision_name} index={activeRevision.customer_index} />
                  )}
                  {activeRevision && phase && <span className="text-slate-600" aria-hidden="true">·</span>}
                  {phase && <span data-testid={`row-phase-${part.id}`}>{phase}</span>}
                </span>
              </div>
              <div className="flex items-center gap-2 min-w-0 text-[11px]">
                <PartNumbers part={{ ...part, customer_part_number: customerNumber }} testIdPrefix={`row-numbers-${part.id}`} className="flex-1" />
                <span className="ml-auto flex-shrink-0 flex items-center gap-2">
                  {article?.mirror_of && (
                    <span data-testid={`tree-mirror-of-${part.id}`} title={`mirror of ${article.mirror_of.part_number}`} className="text-red-300">
                      ⇄<span className="sr-only">mirror of {article.mirror_of.part_number}</span>
                    </span>
                  )}
                  {article && article.mirrored_by.length > 0 && (
                    <span data-testid={`tree-mirrored-by-${part.id}`} title={`mirrored by ${article.mirrored_by.map((m) => m.part_number).join(', ')}`} className="text-red-300">
                      ⇄<span className="sr-only">mirrored by {article.mirrored_by.map((m) => m.part_number).join(', ')}</span>
                    </span>
                  )}
                  {paint && (
                    <span data-testid={`paint-swatch-${part.id}`} className="flex items-center" title="Painted">
                      <ColourSwatch hex={paint.paint.colour_hex} code={paint.paint.colour_code} />
                    </span>
                  )}
                  {hasProposal && (
                    <span data-testid={`row-proposal-${part.id}`} title="Has a proposal" className="text-amber-300">✎</span>
                  )}
                </span>
              </div>
            </div>
          </div>
        </button>
      </div>

      {expanded && hasStructure && (
        <div className="my-1 space-y-1 text-xs" style={{ marginLeft: `${indent + 68}px` }}>
          {article!.revisions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Revisions</span>
              {article!.revisions.map((r) => (
                <button key={r.id} type="button" data-testid={`tree-rev-${r.id}`} onClick={() => onSelectRevision?.(part.id, r.id)}
                  className={`px-1.5 py-0.5 rounded ${r.parent_revision_id ? 'bg-amber-900/40 text-amber-200' : 'bg-slate-700 text-slate-200'} ${r.is_active ? 'font-semibold' : ''}`}>
                  <RevisionLabel name={r.revision_name} index={r.customer_index} />{r.parent_revision_id ? ' proposal' : ''}{r.is_active ? ' ●' : ''}
                </button>
              ))}
            </div>
          )}
          {article!.related.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Linked</span>
              {article!.related.map((r) => (
                <button key={`${r.relation_type}-${r.part_id}`} type="button" data-testid={`tree-rel-${r.part_id}`} onClick={() => onSelect(r.part_id)}
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
            <ItemRow key={child.part.id} {...props} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

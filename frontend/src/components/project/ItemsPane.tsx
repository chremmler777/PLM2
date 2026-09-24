/**
 * ItemsPane - the project's items: search, category filter, collapsible
 * groups of slim rows, and drag-to-restructure onto sub-assemblies. Only the
 * list below the controls scrolls.
 */
import { useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import AssemblyTreeList from '../parts/AssemblyTreeList';
import { apiErrorMessage } from '../../lib/apiError';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import { comparePartNumbers } from '../../lib/partDisplay';
import ItemRow from './ItemRow';
import PartThumbnail from '../parts/PartThumbnail';
import RevisionLabel from '../parts/RevisionLabel';
import { findNode, groupNodes, hasToolFields, matchesSearch, tableRow, visibleOrder, type GroupKey } from './itemGroups';
import {
  CATEGORY_META, buildPartTree, comparePartNodes, getDescendantIds, type Part, type TreeNode,
} from './projectTypes';
import { mirrorConnectors, mirrorGutterWidth } from './mirrorConnectors';

export interface ItemsPaneProps {
  projectId: number;
  projectCode: string;
  parts: Part[] | undefined;
  partsLoading: boolean;
  structure: ProjectStructure | undefined;
  paintByPartId: Map<number, PartPaintLayer>;
  paintedIds: Set<number>;
  paintedCount: number;
  selectedPartId: number | null;
  onSelect(partId: number): void;
  onOpenPart(partId: number): void;
  onPickRevision(partId: number, revisionId: number): void;
  onContextMenu(e: React.MouseEvent, partId: number): void;
  /** 'table' while the detail is popped out: one flat row per item with the key columns. */
  mode?: 'list' | 'table';
}

export default function ItemsPane({
  projectId, projectCode, parts, partsLoading, structure, paintByPartId, paintedIds, paintedCount,
  selectedPartId, onSelect, onOpenPart, onPickRevision, onContextMenu, mode = 'list',
}: ItemsPaneProps) {
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<GroupKey>>(() => new Set());
  // Rows with children start expanded, everything else collapsed; a click overrides.
  const [expandOverride, setExpandOverride] = useState<Record<number, boolean>>({});
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);
  const [hoveredMirrorRowId, setHoveredMirrorRowId] = useState<number | null>(null);

  const reparentMutation = useMutation({
    mutationFn: async ({ partId, parentPartId }: { partId: number; parentPartId: number | null }) => {
      await client.put(`/v1/parts/${partId}`, { parent_part_id: parentPartId });
    },
    onSuccess: () => {
      toast.success('Part moved');
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      queryClient.invalidateQueries({ queryKey: ['assembly-files'] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to move part'));
    },
  });

  const handleDropOnPart = (targetId: number) => {
    if (draggingPartId === null) return;
    const dragged = parts?.find((p) => p.id === draggingPartId);
    if (dragged?.parent_part_id === targetId) {
      setDraggingPartId(null);
      return; // already a child of the target
    }
    reparentMutation.mutate({ partId: draggingPartId, parentPartId: targetId });
    setDraggingPartId(null);
  };

  const invalidDropIds = draggingPartId !== null && parts ? getDescendantIds(parts, draggingPartId) : new Set<number>();

  const query = search.trim();
  const partTree = useMemo(() => (parts ? buildPartTree(parts) : []), [parts]);
  const visibleNodes: TreeNode[] = useMemo(() => {
    if (categoryFilter === 'assemblies' || (categoryFilter === 'all' && !query)) return partTree;
    // A filter or a search lists the matching parts flat, so a hit nested
    // under a non-matching assembly still shows.
    return (parts ?? [])
      .filter((p) => matchesSearch(p, query))
      .filter((p) => categoryFilter === 'all'
        || (categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter))
      .map((p) => ({ part: p, children: [] }))
      .sort(comparePartNodes);
  }, [categoryFilter, query, partTree, parts, paintedIds]);
  const groups = useMemo(() => groupNodes(visibleNodes), [visibleNodes]);
  const tableParts = useMemo(() => (parts ?? [])
    .filter((p) => matchesSearch(p, query))
    .filter((p) => categoryFilter === 'all'
      || (categoryFilter === 'assemblies' ? p.part_type === 'sub_assembly'
        : categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter))
    .sort((a, b) => comparePartNumbers(a.part_number, b.part_number)), [parts, query, categoryFilter, paintedIds]);
  const showCavities = hasToolFields(parts ?? []);
  const isTable = mode === 'table';

  const isExpanded = (n: TreeNode) => expandOverride[n.part.id] ?? n.children.length > 0;
  const setExpanded = (partId: number, next: boolean) =>
    setExpandOverride((o) => ({ ...o, [partId]: next }));
  const toggleGroup = (key: GroupKey) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const listRef = useRef<HTMLDivElement>(null);
  const order = isTable ? tableParts.map((p) => p.id) : visibleOrder(groups, collapsedGroups, isExpanded);
  // Connectors are only rendered in list mode, but computing them off `order` is cheap either way.
  const connectors = useMemo(
    () => mirrorConnectors(order, structure?.articles ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [order.join(','), structure],
  );
  const gutterWidth = useMemo(() => mirrorGutterWidth(connectors), [connectors]);
  const hoveredMirrorPairIds = useMemo(
    () => new Set((hoveredMirrorRowId !== null ? connectors.get(hoveredMirrorRowId) : undefined)?.map((s) => s.pairId) ?? []),
    [hoveredMirrorRowId, connectors],
  );
  const rowExpandable = (n: TreeNode) => {
    const a = articleOf(structure, n.part.id);
    return n.children.length > 0 || (!!a && (a.revisions.length > 0 || a.related.length > 0));
  };

  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('input, select, textarea')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (order.length === 0) return;
      const at = selectedPartId === null ? -1 : order.indexOf(selectedPartId);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      const next = at === -1
        ? (step === 1 ? 0 : order.length - 1)
        : Math.min(order.length - 1, Math.max(0, at + step));
      const nextId = order[next];
      onSelect(nextId);
      listRef.current?.querySelector<HTMLElement>(`[data-row-id="${nextId}"]`)?.scrollIntoView?.({ block: 'nearest' });
      return;
    }
    if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && selectedPartId !== null) {
      if (isTable) return;
      const n = findNode(visibleNodes, selectedPartId);
      if (!n || !rowExpandable(n)) return;
      e.preventDefault();
      setExpanded(selectedPartId, e.key === 'ArrowRight');
    }
  };

  const filtered = categoryFilter !== 'all' || !!query;

  return (
    <div className="h-full flex flex-col min-h-0" data-testid="items-pane">
      <div className="flex-shrink-0 px-3 pt-3 pb-2 space-y-2 border-b border-slate-800">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
            Items ({isTable ? tableParts.length : visibleNodes.length}{filtered ? ` of ${parts?.length ?? 0}` : ''})
          </h2>
          <span className="text-[11px] text-slate-500">Drag onto a ★ sub-assembly to restructure</span>
        </div>
        <input
          type="search"
          aria-label="Search items"
          placeholder="Search number or name"
          value={search}
          disabled={categoryFilter === 'assemblies' && !isTable}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500 disabled:opacity-50"
        />
        <div className="flex flex-wrap gap-1">
          {[['all', 'All'], ...Object.entries(CATEGORY_META).map(([k, v]) => [k, `${v.icon} ${v.label}`]), ['assemblies', '🧩 Assemblies'], ['painted', `🎨 Painted (${paintedCount})`]].map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setCategoryFilter(key)}
                className={`px-2 py-1 rounded text-xs font-medium transition ${
                  categoryFilter === key
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                {label}
              </button>
            )
          )}
        </div>
      </div>

      <div
        ref={listRef}
        data-testid="items-scroll"
        tabIndex={0}
        aria-label="Items"
        onKeyDown={onListKeyDown}
        className="flex-1 min-h-0 overflow-y-auto px-2 py-2 focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-600"
      >
        {isTable ? (
          <table data-testid="items-table" className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-400">
              <tr>
                <th className="px-2 py-1 w-12"><span className="sr-only">Image</span></th>
                {['KTX no.', 'Customer no.', 'Tier 1', 'Name', 'Phase', 'Revision', 'Tool', ...(showCavities ? ['Cavities'] : [])].map((h) => (
                  <th key={h} className="px-2 py-1 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableParts.map((p) => {
                const row = tableRow(p, parts ?? [], structure, projectCode);
                const selected = selectedPartId === p.id;
                return (
                  <tr
                    key={p.id}
                    data-testid={`table-row-${p.id}`}
                    data-row-id={p.id}
                    aria-selected={selected}
                    onClick={() => onSelect(p.id)}
                    onContextMenu={(e) => onContextMenu(e, p.id)}
                    className={`cursor-pointer border-t border-slate-800 ${selected ? 'bg-blue-900/40' : 'hover:bg-slate-800'}`}
                  >
                    <td className="px-2 py-1"><PartThumbnail url={row.thumbnailUrl} name={row.name} testId={`table-thumb-${p.id}`} /></td>
                    <td className="px-2 py-1 font-mono text-slate-200">{row.ktxNumber}</td>
                    <td className="px-2 py-1 font-mono text-slate-200">{row.customerNumber}</td>
                    <td className="px-2 py-1 font-mono text-slate-400">{row.tier1}</td>
                    <td className="px-2 py-1 text-slate-100">{row.name}</td>
                    <td className="px-2 py-1 text-slate-400">{row.phase}</td>
                    <td className="px-2 py-1 font-mono text-slate-300"><RevisionLabel name={row.revisionName} index={row.revisionIndex} /></td>
                    <td className="px-2 py-1 font-mono text-slate-300">{row.tools}</td>
                    {showCavities && <td className="px-2 py-1 text-slate-300">{row.cavities}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : categoryFilter === 'assemblies' ? (
          <AssemblyTreeList projectId={projectId} selectedPartId={selectedPartId} onSelect={onOpenPart} />
        ) : partsLoading ? (
          <p className="text-slate-500 text-sm">Loading...</p>
        ) : (parts?.length ?? 0) === 0 ? (
          <p className="text-slate-500 text-sm">No parts yet</p>
        ) : visibleNodes.length === 0 ? (
          <p className="text-slate-500 text-sm">No items match</p>
        ) : (
          <div className="space-y-2">
            {groups.map((g) => {
              const open = !collapsedGroups.has(g.key);
              return (
                <section key={g.key}>
                  <button
                    type="button"
                    data-testid={`group-toggle-${g.key}`}
                    aria-expanded={open}
                    onClick={() => toggleGroup(g.key)}
                    className="w-full flex items-center gap-2 px-1 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200"
                  >
                    <span className="w-3">{open ? '▾' : '▸'}</span>
                    <span>{g.label}</span>
                    <span className="text-slate-500 font-normal">{g.nodes.length}</span>
                  </button>
                  {open && (
                    <div className="space-y-0.5">
                      {g.nodes.map((node) => (
                        <ItemRow
                          key={node.part.id}
                          node={node}
                          projectCode={projectCode}
                          structure={structure}
                          paintByPartId={paintByPartId}
                          selectedPartId={selectedPartId}
                          isExpanded={isExpanded}
                          onSetExpanded={setExpanded}
                          onSelect={onSelect}
                          onContextMenu={onContextMenu}
                          onSelectRevision={onPickRevision}
                          draggingPartId={draggingPartId}
                          invalidDropIds={invalidDropIds}
                          onDragStartPart={setDraggingPartId}
                          onDragEndPart={() => setDraggingPartId(null)}
                          onDropOnPart={handleDropOnPart}
                          mirrorConnectors={connectors}
                          mirrorGutterWidth={gutterWidth}
                          hoveredMirrorPairIds={hoveredMirrorPairIds}
                          onHoverRow={setHoveredMirrorRowId}
                        />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
            {/* Top-level drop zone, visible while dragging a nested part */}
            {draggingPartId !== null &&
              parts?.find((p) => p.id === draggingPartId)?.parent_part_id != null && (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setTopLevelDragOver(true);
                  }}
                  onDragLeave={() => setTopLevelDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setTopLevelDragOver(false);
                    if (draggingPartId !== null) {
                      reparentMutation.mutate({ partId: draggingPartId, parentPartId: null });
                      setDraggingPartId(null);
                    }
                  }}
                  className={`mt-2 px-3 py-3 rounded border-2 border-dashed text-center text-xs font-medium transition ${
                    topLevelDragOver
                      ? 'border-green-500 bg-green-900/30 text-green-300'
                      : 'border-slate-600 text-slate-400'
                  }`}
                >
                  Drop here to move to top level
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  );
}

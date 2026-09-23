/**
 * ItemsPane - the project's items: category filter, the part tree, and
 * drag-to-restructure onto sub-assemblies.
 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import AssemblyTreeList from '../parts/AssemblyTreeList';
import { apiErrorMessage } from '../../lib/apiError';
import type { ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import ItemRow from './ItemRow';
import {
  CATEGORY_META, buildPartTree, comparePartNodes, getDescendantIds, type Part, type TreeNode,
} from './projectTypes';

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
}

export default function ItemsPane({
  projectId, projectCode, parts, partsLoading, structure, paintByPartId, paintedIds, paintedCount,
  selectedPartId, onSelect, onOpenPart, onPickRevision, onContextMenu,
}: ItemsPaneProps) {
  const id = projectId;
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);

  const reparentMutation = useMutation({
    mutationFn: async ({ partId, parentPartId }: { partId: number; parentPartId: number | null }) => {
      await client.put(`/v1/parts/${partId}`, { parent_part_id: parentPartId });
    },
    onSuccess: () => {
      toast.success('Part moved');
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
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

  const partTree = parts ? buildPartTree(parts) : [];
  const visibleNodes: TreeNode[] = categoryFilter === 'all' || categoryFilter === 'assemblies'
    ? partTree
    : (parts ?? [])
        .filter((p) =>
          categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter
        )
        .map((p) => ({ part: p, children: [] }))
        .sort(comparePartNodes);

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-1">
        Items ({visibleNodes.length}{categoryFilter !== 'all' ? ` of ${parts?.length ?? 0}` : ''})
      </h2>
      <p className="text-xs text-slate-500 mb-2">Drag a part onto a ★ sub-assembly to restructure</p>
      <div className="flex flex-wrap gap-1 mb-3">
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
      {categoryFilter === 'assemblies' ? (
        <AssemblyTreeList projectId={Number(id)} selectedPartId={selectedPartId} onSelect={onOpenPart} />
      ) : partsLoading ? (
        <p className="text-slate-500 text-sm">Loading...</p>
      ) : (parts?.length ?? 0) === 0 ? (
        <p className="text-slate-500 text-sm">No parts yet</p>
      ) : (
        <div className="space-y-1">
          {visibleNodes.map((node) => (
            <ItemRow
              key={node.part.id}
              node={node}
              projectCode={projectCode}
              paintByPartId={paintByPartId}
              selectedPartId={selectedPartId}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              draggingPartId={draggingPartId}
              invalidDropIds={invalidDropIds}
              onDragStartPart={setDraggingPartId}
              onDragEndPart={() => setDraggingPartId(null)}
              onDropOnPart={handleDropOnPart}
              structure={structure}
              onSelectRevision={onPickRevision}
            />
          ))}
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
  );
}

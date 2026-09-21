/**
 * ProjectPaintSection - collapsible project panel listing the painted articles
 * grouped by paint. A part with several layers shows up under each of its
 * paints, with the layer position it occupies there.
 */
import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { projectPaintOverview } from '../../api/paints';
import { PAINT_TYPE_LABEL, type Paint, type PaintOverviewPart } from '../../types/paint';
import ColourSwatch from './ColourSwatch';

interface PaintGroup {
  paint: Paint;
  rows: { part_id: number; part_number: string; name: string; layer_order: number }[];
}

// One group per paint, in first-seen order; a part contributes one row per
// layer that uses the paint.
function groupByPaint(parts: PaintOverviewPart[]): PaintGroup[] {
  const groups = new Map<number, PaintGroup>();
  for (const part of parts) {
    for (const layer of part.layers) {
      let group = groups.get(layer.paint.id);
      if (!group) {
        group = { paint: layer.paint, rows: [] };
        groups.set(layer.paint.id, group);
      }
      group.rows.push({
        part_id: part.part_id,
        part_number: part.part_number,
        name: part.name,
        layer_order: layer.layer_order,
      });
    }
  }
  return [...groups.values()];
}

export default function ProjectPaintSection({ projectId }: { projectId: number }) {
  const [expanded, setExpanded] = useState(false);

  const { data: overview } = useQuery({
    queryKey: ['project-paint-overview', projectId],
    queryFn: () => projectPaintOverview(projectId),
  });

  const groups = useMemo(() => groupByPaint(overview ?? []), [overview]);

  return (
    <div className="mb-4 bg-slate-800 rounded-lg border border-slate-700 p-3">
      <button
        type="button"
        data-testid="project-paint-toggle"
        onClick={() => setExpanded(!expanded)}
        className="text-sm font-semibold text-slate-300"
      >
        🎨 Paint ({overview?.length ?? 0}) {expanded ? '▾' : '▸'}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {groups.length === 0 ? (
            <p className="text-xs text-slate-500">No painted articles yet</p>
          ) : (
            groups.map((group) => (
              <div key={group.paint.id} data-testid={`paint-group-${group.paint.id}`}>
                <div className="flex items-center gap-2 text-sm text-slate-200">
                  <ColourSwatch hex={group.paint.colour_hex} code={group.paint.colour_code} />
                  <span className="font-semibold">{group.paint.name}</span>
                  <span className="text-xs text-slate-400">
                    {PAINT_TYPE_LABEL[group.paint.paint_type] ?? group.paint.paint_type}
                  </span>
                  {group.paint.colour_code && (
                    <span className="text-xs text-slate-500">{group.paint.colour_code}</span>
                  )}
                  {!group.paint.is_active && <span className="text-red-400 text-xs">inactive</span>}
                </div>
                <div className="mt-1 space-y-1">
                  {group.rows.map((row) => (
                    <div
                      key={`${row.part_id}-${row.layer_order}`}
                      className="flex items-center gap-2 px-2 py-1 rounded bg-slate-900/40 text-sm"
                    >
                      <span className="text-slate-400 text-xs">{row.part_number}</span>
                      <span className="text-slate-200 truncate">{row.name}</span>
                      <span className="ml-auto text-xs text-slate-500 flex-shrink-0">
                        Layer {row.layer_order}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/**
 * ProcessFlowSection - the tool's process route, derived from serves/feeds
 * relations: mold -> EOAT -> in-cell -> secondary -> gauge, with upstream tools
 * merging in. Nothing is stored, so the flow cannot drift from the equipment.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

interface Station {
  id: number;
  part_number: string;
  name: string;
  op_code: string;
  kind: string;
  serves: string[];
}

interface FlowPart {
  id: number;
  part_number: string;
  name: string;
  note?: string | null;
}

interface Flow {
  tool: FlowPart;
  upstream: FlowPart[];
  downstream: FlowPart[];
  stations: Station[];
}

interface Props {
  partId: number;
  onSelectPart?: (partId: number) => void;
}

const KIND_LABEL: Record<string, string> = {
  eoat: 'EOAT',
  in_cell_station: 'In-cell',
  secondary_station: 'Secondary',
  gauge: 'Gauge',
};

const KIND_ACCENT: Record<string, string> = {
  eoat: 'border-sky-700',
  in_cell_station: 'border-amber-700',
  secondary_station: 'border-violet-700',
  gauge: 'border-emerald-700',
};

function Node({
  number, name, sub, accent, onClick,
}: {
  number: string; name: string; sub?: string; accent?: string;
  onClick?: () => void;
}) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      data-testid="flow-node"
      onClick={onClick}
      className={`min-w-[9rem] max-w-[13rem] text-left rounded border ${
        accent ?? 'border-slate-600'
      } bg-slate-900 px-3 py-2 ${onClick ? 'hover:bg-slate-700' : ''}`}
    >
      <div className="font-mono text-xs text-slate-100">{number}</div>
      <div className="text-xs text-slate-300 truncate" title={name}>{name}</div>
      {sub && <div className="mt-1 text-[11px] text-slate-400">{sub}</div>}
    </Tag>
  );
}

export default function ProcessFlowSection({ partId, onSelectPart }: Props) {
  const { data, isLoading } = useQuery<Flow>({
    queryKey: ['process-flow', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/process-flow`)).data,
    enabled: !!partId,
  });

  if (isLoading || !data) return null;

  const empty = data.stations.length === 0
    && data.upstream.length === 0 && data.downstream.length === 0;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">Process</h3>

      {empty ? (
        <p className="text-slate-500 text-xs">
          No equipment recorded for this tool yet.
        </p>
      ) : (
        <div className="space-y-3">
          {data.upstream.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-slate-400">
                Feeds in
              </span>
              {data.upstream.map((u) => (
                <Node
                  key={u.id} number={u.part_number} name={u.name}
                  sub={u.note ?? undefined}
                  onClick={onSelectPart ? () => onSelectPart(u.id) : undefined}
                />
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 overflow-x-auto">
            <Node number={data.tool.part_number} name={data.tool.name} sub="Mold" />
            {data.stations.map((s) => (
              <div key={s.id} className="flex items-center gap-2">
                <span aria-hidden className="text-slate-500">→</span>
                <Node
                  number={s.part_number} name={s.name}
                  accent={KIND_ACCENT[s.kind]}
                  sub={[
                    KIND_LABEL[s.kind] ?? s.kind,
                    s.serves.length > 1 ? `shared: ${s.serves.join(', ')}` : null,
                  ].filter(Boolean).join(' · ')}
                  onClick={onSelectPart ? () => onSelectPart(s.id) : undefined}
                />
              </div>
            ))}
          </div>

          {data.downstream.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-slate-400">
                Feeds into
              </span>
              {data.downstream.map((d) => (
                <Node
                  key={d.id} number={d.part_number} name={d.name}
                  sub={d.note ?? undefined}
                  onClick={onSelectPart ? () => onSelectPart(d.id) : undefined}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

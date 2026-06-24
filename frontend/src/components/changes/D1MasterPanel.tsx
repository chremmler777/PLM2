import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { Gate, GateKey } from '../../types/change';
import { t } from '../../i18n/cmLabels';

const GATES: GateKey[] = ['feasibility', 'budget', 'release'];

export default function D1MasterPanel({ changeId }: { changeId: number }) {
  const qc = useQueryClient();
  const { data: gates = [] } = useQuery({
    queryKey: ['change-gates', changeId], queryFn: () => changesApi.getGates(changeId) });
  const decide = useMutation({
    mutationFn: ({ key, decision }: { key: GateKey; decision: string }) =>
      changesApi.putGate(changeId, key, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-gates', changeId] }),
  });
  const byKey: Record<string, Gate> = Object.fromEntries(gates.map((g) => [g.gate_key, g]));

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-2">
      <div className="font-semibold text-slate-100">Final assessment</div>
      {GATES.map((key) => {
        const g = byKey[key];
        return (
          <div key={key} className="flex items-center justify-between text-sm">
            <span className="text-slate-200">{t(key)}</span>
            <span className="flex gap-1">
              {(['yes', 'no', 'na'] as const).map((d) => (
                <button key={d} onClick={() => decide.mutate({ key, decision: d })}
                  className={`px-2 py-0.5 rounded text-xs border ${g?.decision === d
                    ? 'bg-sky-600 text-white border-sky-500'
                    : 'bg-slate-900 text-slate-300 border-slate-600'}`}>{d}</button>
              ))}
            </span>
          </div>
        );
      })}
    </div>
  );
}

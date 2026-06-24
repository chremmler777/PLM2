import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { CostLine, CostLineIn, CostKind, DepartmentRateRef } from '../../types/change';
import { t } from '../../i18n/cmLabels';

// ── pure helper (exported for unit tests) ────────────────────────────────────

export function internalCost(
  rates: DepartmentRateRef[],
  departmentId: number,
  plantId: number,
  hours: number,
): number {
  const r = rates.find((x) => x.department_id === departmentId && x.plant_id === plantId);
  return r ? hours * r.hourly_rate : 0;
}

// ── local row type ────────────────────────────────────────────────────────────

type Row = CostLineIn & { _internal: number };

function makeRow(plantId: number): Row {
  return {
    plant_id: plantId,
    cost_kind: 'one_time',
    demand_hours: 0,
    external_cost: 0,
    activity_id: null,
    activity_label: '',
    note: null,
    _internal: 0,
  };
}

function lineToRow(l: CostLine, rates: DepartmentRateRef[], departmentId: number): Row {
  return {
    plant_id: l.plant_id,
    cost_kind: l.cost_kind,
    demand_hours: l.demand_hours,
    external_cost: l.external_cost,
    activity_id: l.activity_id ?? null,
    activity_label: l.activity_label ?? '',
    note: l.note ?? null,
    _internal: l.internal_cost,
    // recalc from live rates when available so UI is consistent
    ...(rates.length > 0
      ? { _internal: internalCost(rates, departmentId, l.plant_id, l.demand_hours) }
      : {}),
  };
}

// ── component ─────────────────────────────────────────────────────────────────

interface CostLineGridProps {
  changeId: number;
  assessmentId: number;
  departmentId: number;
  plants: { id: number; name: string }[];
}

export default function CostLineGrid({
  changeId,
  assessmentId,
  departmentId,
  plants,
}: CostLineGridProps) {
  const qc = useQueryClient();

  const { data: rates = [] } = useQuery({
    queryKey: ['cm-rates'],
    queryFn: changesApi.referenceRates,
  });

  const { data: activities = [] } = useQuery({
    queryKey: ['cm-activities', departmentId],
    queryFn: () => changesApi.referenceActivities(departmentId),
  });

  const { data: existing = [] } = useQuery({
    queryKey: ['cost-lines', changeId, assessmentId],
    queryFn: () => changesApi.getCostLines(changeId, assessmentId),
  });

  const [rows, setRows] = useState<Row[]>([]);
  const [seeded, setSeeded] = useState(false);

  // Seed rows from server data once, after both existing lines and rates are loaded
  useEffect(() => {
    if (!seeded && existing.length > 0) {
      setRows(existing.map((l: CostLine) => lineToRow(l, rates, departmentId)));
      setSeeded(true);
    }
  }, [existing, rates, seeded, departmentId]);

  const save = useMutation({
    mutationFn: () =>
      changesApi.putCostLines(
        changeId,
        assessmentId,
        // strip the _internal field — it is not part of CostLineIn
        rows.map(({ _internal: _omit, ...l }) => l as CostLineIn),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost-lines', changeId, assessmentId] });
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] });
    },
  });

  const addRow = () =>
    setRows((r) => [...r, makeRow(plants[0]?.id ?? 0)]);

  const update = (i: number, patch: Partial<Row>) =>
    setRows((r) =>
      r.map((row, j) => {
        if (j !== i) return row;
        const merged = { ...row, ...patch };
        // Recompute internal cost whenever hours or plant changes
        merged._internal = internalCost(rates, departmentId, merged.plant_id, merged.demand_hours);
        return merged;
      }),
    );

  const removeRow = (i: number) => setRows((r) => r.filter((_, j) => j !== i));

  // Per-plant totals
  const plantTotals: Record<number, { internal: number; external: number }> = {};
  for (const p of plants) plantTotals[p.id] = { internal: 0, external: 0 };
  let grandTotal = 0;
  for (const row of rows) {
    if (plantTotals[row.plant_id]) {
      plantTotals[row.plant_id].internal += row._internal;
      plantTotals[row.plant_id].external += row.external_cost || 0;
    }
    grandTotal += row._internal + (row.external_cost || 0);
  }

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-2">
      <table className="w-full text-sm text-slate-200">
        <thead>
          <tr className="text-xs text-slate-400 border-b border-slate-700">
            <th className="text-left pb-1">{t('activity')}</th>
            <th className="text-left pb-1">{t('plant')}</th>
            <th className="text-left pb-1">{t('kind')}</th>
            <th className="text-right pb-1">{t('hours')}</th>
            <th className="text-right pb-1">{t('internal')}</th>
            <th className="text-right pb-1">{t('external')}</th>
            <th className="pb-1"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-800">
              {/* Activity */}
              <td className="py-1 pr-1">
                <input
                  list={`acts-${i}`}
                  className="bg-slate-900 border border-slate-600 rounded px-1 w-full text-slate-100 text-xs"
                  value={row.activity_label ?? ''}
                  onChange={(e) => update(i, { activity_label: e.target.value })}
                  placeholder="Activity…"
                />
                <datalist id={`acts-${i}`}>
                  {activities.map((a) => (
                    <option key={a.id} value={a.label} />
                  ))}
                </datalist>
              </td>
              {/* Plant */}
              <td className="py-1 pr-1">
                <select
                  className="bg-slate-900 border border-slate-600 rounded px-1 text-slate-100 text-xs"
                  value={row.plant_id}
                  onChange={(e) => update(i, { plant_id: Number(e.target.value) })}
                >
                  {plants.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </td>
              {/* Cost kind */}
              <td className="py-1 pr-1">
                <select
                  className="bg-slate-900 border border-slate-600 rounded px-1 text-slate-100 text-xs"
                  value={row.cost_kind}
                  onChange={(e) => update(i, { cost_kind: e.target.value as CostKind })}
                >
                  <option value="one_time">{t('one_time')}</option>
                  <option value="lifecycle">{t('lifecycle')}</option>
                </select>
              </td>
              {/* Demand hours */}
              <td className="py-1 pr-1">
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  className="bg-slate-900 border border-slate-600 rounded w-16 text-right px-1 text-slate-100 text-xs"
                  value={row.demand_hours}
                  onChange={(e) => update(i, { demand_hours: Number(e.target.value) })}
                />
              </td>
              {/* Internal (auto) */}
              <td className="py-1 pr-1 text-right text-slate-400 text-xs tabular-nums">
                {row._internal.toFixed(2)}
              </td>
              {/* External */}
              <td className="py-1 pr-1">
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  className="bg-slate-900 border border-slate-600 rounded w-20 text-right px-1 text-slate-100 text-xs"
                  value={row.external_cost}
                  onChange={(e) => update(i, { external_cost: Number(e.target.value) })}
                />
              </td>
              {/* Remove */}
              <td className="py-1">
                <button
                  onClick={() => removeRow(i)}
                  className="text-slate-500 hover:text-rose-400 text-xs px-1"
                  title="Remove row"
                  aria-label="Remove row"
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        {/* Per-plant footer */}
        {plants.length > 1 && rows.length > 0 && (
          <tfoot>
            {plants.map((p) => {
              const pt = plantTotals[p.id];
              if (!pt || (pt.internal === 0 && pt.external === 0)) return null;
              return (
                <tr key={p.id} className="text-xs text-slate-500 border-t border-slate-800">
                  <td colSpan={4} className="text-right pr-1 pt-1 italic">
                    {p.name}
                  </td>
                  <td className="text-right tabular-nums pt-1">{pt.internal.toFixed(2)}</td>
                  <td className="text-right tabular-nums pt-1">{pt.external.toFixed(2)}</td>
                  <td />
                </tr>
              );
            })}
          </tfoot>
        )}
      </table>

      {/* Actions + grand total */}
      <div className="flex items-center justify-between pt-1">
        <button
          onClick={addRow}
          className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-100"
        >
          + row
        </button>
        <span className="text-sm text-slate-300 tabular-nums">
          {t('total')}: {grandTotal.toFixed(2)}
        </span>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="px-2.5 py-1 text-xs rounded bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50"
        >
          {save.isPending ? t('saving') : t('save')}
        </button>
      </div>
    </div>
  );
}

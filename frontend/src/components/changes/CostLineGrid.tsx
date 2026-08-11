/**
 * The department's cost sheet, laid out like the workbook it replaces: activities
 * down the side, one column group per affected plant, internal hours and external
 * money side by side, the ongoing production-time delta in its own block, and the
 * sums along the bottom.
 *
 * Underneath it is still one line per activity × plant × kind — the matrix is
 * presentation. Rows arrive pre-seeded from what the department ticked in its
 * assessment; anything else is added here.
 */
import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { CostLine, CostLineIn, DepartmentRateRef } from '../../types/change';
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

// ── matrix model ─────────────────────────────────────────────────────────────

interface ActivityRow {
  /** Catalog id, or null for a free line. */
  activityId: number | null;
  label: string;
}

/** One editable cell: what a plant costs for one activity, one kind. */
interface Cell {
  hours: number;
  external: number;
  minutes: number;
  note?: string | null;
}

const EMPTY: Cell = { hours: 0, external: 0, minutes: 0 };
const rowKey = (r: ActivityRow) => (r.activityId != null ? `a${r.activityId}` : `f:${r.label}`);
const cellKey = (r: ActivityRow, plantId: number) => `${rowKey(r)}|${plantId}`;

function readLines(lines: CostLine[]): { rows: ActivityRow[]; cells: Record<string, Cell> } {
  const rows: ActivityRow[] = [];
  const cells: Record<string, Cell> = {};
  for (const l of lines) {
    const row: ActivityRow = {
      activityId: l.activity_id ?? null,
      label: l.activity_label ?? '',
    };
    if (!rows.some((r) => rowKey(r) === rowKey(row))) rows.push(row);
    const k = cellKey(row, l.plant_id);
    const cur = cells[k] ?? { ...EMPTY };
    cells[k] = {
      hours: cur.hours + (l.cost_kind === 'one_time' ? l.demand_hours : 0),
      external: cur.external + l.external_cost,
      minutes: cur.minutes + (l.cost_kind === 'lifecycle' ? l.minutes_per_part ?? 0 : 0),
      note: l.note ?? cur.note,
    };
  }
  return { rows, cells };
}

/** Back to the wire format: one line per activity × plant × kind, empties dropped. */
export function toLines(
  rows: ActivityRow[], cells: Record<string, Cell>, plantIds: number[],
): CostLineIn[] {
  const out: CostLineIn[] = [];
  for (const r of rows) {
    for (const plantId of plantIds) {
      const c = cells[cellKey(r, plantId)] ?? EMPTY;
      const base = {
        plant_id: plantId,
        activity_id: r.activityId,
        activity_label: r.label,
        note: c.note ?? null,
      };
      if (c.hours || c.external) {
        out.push({ ...base, cost_kind: 'one_time', demand_hours: c.hours, external_cost: c.external });
      }
      if (c.minutes) {
        out.push({
          ...base, cost_kind: 'lifecycle', demand_hours: 0, external_cost: 0,
          minutes_per_part: c.minutes,
        });
      }
    }
  }
  return out;
}

// ── component ─────────────────────────────────────────────────────────────────

interface CostLineGridProps {
  changeId: number;
  assessmentId: number;
  departmentId: number;
  /** The change's affected plants — these and only these become columns. */
  plants: { id: number; name: string; is_active?: boolean }[];
  projectPlantId?: number | null;
}

export default function CostLineGrid({
  changeId, assessmentId, departmentId, plants,
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

  // Only plants this department has a rate for can be costed; anything else
  // would silently price at zero.
  const ratedPlantIds = new Set(
    rates.filter((r) => r.department_id === departmentId).map((r) => r.plant_id),
  );
  const columns = rates.length === 0
    ? plants
    : plants.filter((p) => ratedPlantIds.has(p.id));

  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [cells, setCells] = useState<Record<string, Cell>>({});
  const [seeded, setSeeded] = useState(false);
  const [adding, setAdding] = useState(false);

  // Seed once from the server: the lines costing pre-filled from the assessment.
  useEffect(() => {
    if (seeded || existing.length === 0) return;
    const parsed = readLines(existing as CostLine[]);
    setRows(parsed.rows);
    setCells(parsed.cells);
    setSeeded(true);
  }, [existing, seeded]);

  const save = useMutation({
    mutationFn: () => changesApi.putCostLines(
      changeId, assessmentId, toLines(rows, cells, columns.map((p) => p.id))),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost-lines', changeId, assessmentId] });
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] });
    },
  });

  const cellOf = (r: ActivityRow, plantId: number) => cells[cellKey(r, plantId)] ?? EMPTY;
  const setCell = (r: ActivityRow, plantId: number, patch: Partial<Cell>) =>
    setCells((c) => ({ ...c, [cellKey(r, plantId)]: { ...(c[cellKey(r, plantId)] ?? EMPTY), ...patch } }));

  const addRow = (label: string, activityId: number | null) => {
    const row = { activityId, label: label.trim() };
    if (!row.label) return;
    setRows((rs) => (rs.some((x) => rowKey(x) === rowKey(row)) ? rs : [...rs, row]));
    setAdding(false);
  };
  const removeRow = (r: ActivityRow) => {
    setRows((rs) => rs.filter((x) => rowKey(x) !== rowKey(r)));
    setCells((c) => Object.fromEntries(
      Object.entries(c).filter(([k]) => !k.startsWith(`${rowKey(r)}|`))));
  };

  const plantSum = (plantId: number) => rows.reduce((sum, r) => {
    const c = cellOf(r, plantId);
    return sum + internalCost(rates, departmentId, plantId, c.hours) + c.external;
  }, 0);
  const grandTotal = columns.reduce((s, p) => s + plantSum(p.id), 0);
  const plantMinutes = (plantId: number) =>
    rows.reduce((sum, r) => sum + cellOf(r, plantId).minutes, 0);

  if (rates.length > 0 && columns.length === 0) {
    return (
      <div className="rounded border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-400">
        {t('no_rate_configured')}
      </div>
    );
  }

  const numberCell = (
    testid: string, value: number, onChange: (v: number) => void,
    opts: { step?: number; min?: number; label: string; width?: string } = { label: '' },
  ) => (
    <input type="number" data-testid={testid} aria-label={opts.label}
      step={opts.step ?? 0.5} min={opts.min}
      value={value || ''}
      onChange={(e) => onChange(Number(e.target.value || 0))}
      className={`${opts.width ?? 'w-16'} bg-slate-900 border border-slate-600 rounded px-1 text-right text-slate-100 text-xs`} />
  );

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-3 overflow-x-auto">
      <table className="w-full text-sm text-slate-200">
        <thead>
          {/* Plants across the top, exactly the ones this change affects. */}
          <tr className="text-xs text-slate-400">
            <th rowSpan={2} className="text-left pb-1 pr-2 align-bottom">{t('costing.activity')}</th>
            {columns.map((p) => (
              <th key={p.id} colSpan={3} data-testid={`plant-col-${p.id}`}
                className="pb-1 px-1 text-center border-l border-slate-700">
                {p.name}
              </th>
            ))}
            <th rowSpan={2} />
          </tr>
          <tr className="text-[11px] text-slate-500">
            {columns.map((p) => (
              <>
                <th key={`${p.id}-h`} className="pb-1 px-1 text-right border-l border-slate-700">
                  {t('hours')}
                </th>
                <th key={`${p.id}-i`} className="pb-1 px-1 text-right">{t('internal')}</th>
                <th key={`${p.id}-e`} className="pb-1 px-1 text-right">{t('external')}</th>
              </>
            ))}
          </tr>
        </thead>

        <tbody>
          <tr>
            <td colSpan={1 + columns.length * 3 + 1}
              className="pt-2 pb-1 text-[11px] uppercase tracking-wide text-slate-500">
              {t('costing.oneTimeSection')}
            </td>
          </tr>
          {rows.map((r) => (
            <tr key={rowKey(r)} data-testid={`cost-row-${rowKey(r)}`}
              className="border-b border-slate-800">
              <td className="py-1 pr-2 text-slate-200">{r.label}</td>
              {columns.map((p) => {
                const c = cellOf(r, p.id);
                return (
                  <>
                    <td key={`${p.id}-h`} className="py-1 px-1 text-right border-l border-slate-700">
                      {numberCell(`hours-${rowKey(r)}-${p.id}`, c.hours,
                        (v) => setCell(r, p.id, { hours: v }), { min: 0, label: t('hours') })}
                    </td>
                    <td key={`${p.id}-i`}
                      data-testid={`internal-${rowKey(r)}-${p.id}`}
                      className="py-1 px-1 text-right text-slate-400 text-xs tabular-nums">
                      {internalCost(rates, departmentId, p.id, c.hours).toFixed(2)}
                    </td>
                    <td key={`${p.id}-e`} className="py-1 px-1 text-right">
                      {numberCell(`external-${rowKey(r)}-${p.id}`, c.external,
                        (v) => setCell(r, p.id, { external: v }),
                        { min: 0, step: 0.01, label: t('external'), width: 'w-20' })}
                    </td>
                  </>
                );
              })}
              <td className="py-1 pl-1">
                <button onClick={() => removeRow(r)} aria-label={`Remove ${r.label}`}
                  className="text-slate-600 hover:text-rose-400 text-xs">×</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={1 + columns.length * 3 + 1} className="py-2 text-xs text-slate-500">
              {t('costing.noActivities')}
            </td></tr>
          )}

          {/* Ongoing production time is a different question about the same
              activities, so it gets its own block rather than a stray column. */}
          {rows.length > 0 && (
            <>
              <tr>
                <td colSpan={1 + columns.length * 3 + 1}
                  className="pt-3 pb-1 text-[11px] uppercase tracking-wide text-slate-500">
                  {t('costing.lifecycleSection')}
                  <span className="ml-2 normal-case text-slate-600">{t('costing.minutesHint')}</span>
                </td>
              </tr>
              {rows.map((r) => (
                <tr key={`lc-${rowKey(r)}`} data-testid={`lifecycle-row-${rowKey(r)}`}
                  className="border-b border-slate-800">
                  <td className="py-1 pr-2 text-slate-300">{r.label}</td>
                  {columns.map((p) => (
                    <td key={p.id} colSpan={3}
                      className="py-1 px-1 text-right border-l border-slate-700">
                      {numberCell(`minutes-${rowKey(r)}-${p.id}`, cellOf(r, p.id).minutes,
                        (v) => setCell(r, p.id, { minutes: v }),
                        { step: 0.1, label: t('costing.minutes'), width: 'w-20' })}
                      <span className="ml-1 text-[10px] text-slate-500">
                        {t('costing.minutesShort')}
                      </span>
                    </td>
                  ))}
                  <td />
                </tr>
              ))}
            </>
          )}
        </tbody>

        <tfoot>
          <tr className="border-t border-slate-600 text-slate-200">
            <td className="pt-1 pr-2 text-xs font-semibold">{t('costing.sum')}</td>
            {columns.map((p) => (
              <td key={p.id} colSpan={3} data-testid={`plant-sum-${p.id}`}
                className="pt-1 px-1 text-right tabular-nums border-l border-slate-700">
                {plantSum(p.id).toFixed(2)}
                {plantMinutes(p.id) !== 0 && (
                  <span className="block text-[10px] text-slate-500">
                    {plantMinutes(p.id) > 0 ? '+' : ''}{plantMinutes(p.id)} {t('costing.minutesShort')}
                  </span>
                )}
              </td>
            ))}
            <td />
          </tr>
        </tfoot>
      </table>

      <div className="flex items-center justify-between gap-3">
        {adding ? (
          <input type="text" autoFocus list={`acts-${departmentId}`}
            data-testid="cost-add-input" aria-label={t('costing.activity')}
            placeholder={t('costing.activityPlaceholder')}
            onBlur={(e) => {
              const match = activities.find((a) => a.label === e.target.value.trim());
              addRow(e.target.value, match?.id ?? null);
            }}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
        ) : (
          <button data-testid="cost-add-row" onClick={() => setAdding(true)}
            className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-100">
            {t('costing.addActivity')}
          </button>
        )}
        <datalist id={`acts-${departmentId}`}>
          {activities.map((a) => <option key={a.id} value={a.label} />)}
        </datalist>
        <span className="text-sm text-slate-300 tabular-nums" data-testid="cost-grand-total">
          {t('total')}: {grandTotal.toFixed(2)}
        </span>
        <button onClick={() => save.mutate()} disabled={save.isPending}
          className="px-2.5 py-1 text-xs rounded bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50">
          {save.isPending ? t('saving') : t('save')}
        </button>
      </div>
    </div>
  );
}

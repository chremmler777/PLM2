/**
 * The MachineDB presses on the Machines tab: the synced copy of MachineDB's
 * machine list, grouped by plant, each with an optional hourly rate of its
 * own in the selected version. A machine without its own rate is priced on
 * the class rate of its plant (the table above), shown here for reference.
 *
 * MachineDB is read through a sync (Sales, Finance or admin). When the
 * server has no MachineDB connection the table keeps the last synced copy.
 */
import { useEffect, useId, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RefreshCw, X } from 'lucide-react'
import { costSheetApi } from '../../api/costSheet'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import { apiErrorMessage, toastError } from '../../lib/apiError'
import {
  NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, formatDateTime, formatMoney, formatNumber, readNumberInput,
} from '../../lib/format'
import { btnSm } from '../common/buttonStyles'
import ColumnHeader from '../common/ColumnHeader'
import ConfirmDialog from '../common/ConfirmDialog'
import TableFilterBar from '../common/TableFilterBar'
import {
  applyTableState, ariaSort, useTableState, type FilterColumnDef,
} from '../common/tableFilters'
import type {
  CostSheetMachine, MachineSyncResult, MachinesListing,
} from '../../types/costSheetMachines'
import type { PlantCurrency } from '../../types/costSheet'

interface Props {
  versionId: number | null
  /** The selected version is a draft and the user may edit the sheet. */
  editable: boolean
  plants: PlantCurrency[]
}

const TWO_K: Record<string, string> = {
  '2k_turntable': '2K turntable', '2k_no_turntable': '2K no turntable',
  parallel_injection: 'Parallel injection',
}
const UNMAPPED = 'Not mapped to a plant'

export function machineStatus(m: CostSheetMachine): 'Active' | 'Scrapped' | 'Retired' {
  if (m.retired) return 'Retired'
  return m.active ? 'Active' : 'Scrapped'
}

export default function MachinesPanel({ versionId, editable, plants }: Props) {
  const qc = useQueryClient()
  const key = ['cost-sheet', 'machines', versionId]
  const q = useQuery({
    queryKey: key,
    queryFn: () => costSheetMachinesApi.list({ version_id: versionId }),
  })
  const [report, setReport] = useState<MachineSyncResult | null>(null)
  const plantName = useMemo(() => {
    const m = new Map(plants.map((p) => [p.id, p.name]))
    return (id: number | null) => (id == null ? UNMAPPED : m.get(id) ?? `Plant ${id}`)
  }, [plants])

  const sync = useMutation({
    mutationFn: (force: boolean) => costSheetMachinesApi.sync(force),
    onSuccess: (res) => {
      setReport(res)
      qc.invalidateQueries({ queryKey: ['cost-sheet', 'machines'] })
      toast.success(`Synced ${res.total ?? 0} machines from MachineDB`)
    },
    onError: (e) => {
      qc.invalidateQueries({ queryKey: ['cost-sheet', 'machines'] })
      toastError(e, 'Could not sync from MachineDB')
    },
  })

  if (q.isLoading) {
    return <p className="text-sm text-slate-500" aria-busy="true">Loading the machines</p>
  }
  if (q.isError || !q.data) {
    return (
      <div role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
        {apiErrorMessage(q.error, 'Could not load the machines')}
        <button type="button" onClick={() => q.refetch()} className={`${btnSm.ghost} ml-3`}>Try again</button>
      </div>
    )
  }
  const data = q.data
  return (
    <section aria-labelledby="machinedb-heading" className="space-y-3 pt-2">
      <SyncBar data={data} busy={sync.isPending} onSync={(force) => sync.mutate(force)} />
      {report && <SyncReport report={report} plantName={plantName} onClose={() => setReport(null)} />}
      <PlantMapping data={data} plants={plants} />
      <MachineTable data={data} versionId={versionId} editable={editable && data.can_edit_rates}
        plantName={plantName} />
    </section>
  )
}

// ---------------------------------------------------------------- sync bar

function SyncBar({ data, busy, onSync }: { data: MachinesListing; busy: boolean; onSync: (force: boolean) => void }) {
  const last = data.last_sync
  const cfg = data.machinedb
  const failedLast = !!last?.failed_at && (!last.at || last.failed_at > last.at)
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 space-y-0.5">
        <h2 id="machinedb-heading" className="text-base font-semibold text-slate-100">Machines from MachineDB</h2>
        <p className="max-w-3xl text-sm text-slate-500">
          A rate here is the machine&apos;s own hourly rate in this version. It beats the class rate
          wherever a costing line names the machine; machines without one use their class rate.
        </p>
        <p className="text-xs text-slate-400" data-testid="machinedb-last-sync">
          {last?.at
            ? <>Last synced {formatDateTime(last.at)} · {last.total ?? 0} machines</>
            : 'Never synced'}
          {!cfg.configured && (
            <span className="text-amber-300"> · Sync is off: the server has no MachineDB connection
              ({cfg.missing.join(' and ')} not set). The table shows the last synced copy.</span>
          )}
        </p>
        {failedLast && (
          <p role="status" className="text-xs text-amber-300" data-testid="machinedb-last-error">
            Last sync failed {formatDateTime(last!.failed_at!)}: {last!.error}
            {last!.guard && data.can_sync && cfg.configured && (
              <button type="button" disabled={busy}
                className="ml-2 font-medium text-amber-200 underline underline-offset-2 hover:text-amber-100 disabled:opacity-60"
                onClick={() => {
                  if (window.confirm('Apply what MachineDB sends now? Machines it no longer lists are retired; their rates and costing lines stay.')) onSync(true)
                }}>
                Sync anyway
              </button>
            )}
          </p>
        )}
      </div>
      {data.can_sync && (
        <button type="button" onClick={() => onSync(false)} disabled={busy || !cfg.configured}
          title={cfg.configured ? `Read the machine list from ${cfg.host ?? 'MachineDB'}` : 'MachineDB is not configured on the server'}
          className={`${btnSm.primary} inline-flex items-center gap-1.5`}>
          <RefreshCw aria-hidden="true" size={13} className={busy ? 'animate-spin' : ''} />
          {busy ? 'Syncing' : 'Sync from MachineDB'}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- report

function SyncReport({ report, plantName, onClose }: {
  report: MachineSyncResult; plantName: (id: number | null) => string; onClose: () => void
}) {
  const r = report.report
  const groups: [string, string[]][] = [
    ['New', r.new.map((m) => `${m.internal_name} (${plantName(m.plant_id)})`)],
    ['Changed', r.changed.map((m) => `${m.internal_name}: ${(m.fields ?? []).join(', ').replace(/_/g, ' ')}`)],
    ['Scrapped', r.scrapped.map((m) => m.internal_name)],
    ['No longer in MachineDB', r.retired.map((m) => m.internal_name)],
    ['Back in MachineDB', r.returned.map((m) => m.internal_name)],
    ['Unmapped plant', r.unmapped.map((u) => `${u.machinedb_plant}: ${u.count} machine${u.count === 1 ? '' : 's'}`)],
    ['Skipped rows', r.skipped],
  ]
  const shown = groups.filter(([, items]) => items.length > 0)
  return (
    <div role="status" data-testid="machinedb-sync-report"
      className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-slate-200">
          Sync report: {report.total ?? 0} machines, {report.new ?? 0} new, {report.changed ?? 0} changed,
          {' '}{report.retired ?? 0} retired or scrapped, {report.unmapped ?? 0} without a plant
        </p>
        <button type="button" onClick={onClose} aria-label="Close the sync report"
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-700/60 hover:text-slate-200">
          <X aria-hidden="true" size={14} />
        </button>
      </div>
      {shown.length === 0 ? (
        <p className="mt-1 text-slate-400">Nothing changed since the last sync.</p>
      ) : (
        <dl className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-[max-content_1fr]">
          {shown.map(([label, items]) => (
            <div key={label} className="contents">
              <dt className="text-slate-400">{label}</dt>
              <dd className="text-slate-200">{items.slice(0, 12).join(' · ')}{items.length > 12 ? ` and ${items.length - 12} more` : ''}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- plant mapping

/** Why a MachineDB plant maps where it does, in words. */
function mapSource(e: { plant_id: number | null; source: string }): string {
  if (e.source === 'setting') return e.plant_id == null ? 'kept unmapped by hand' : 'mapped by hand'
  if (e.source === 'default') return 'by plant name'
  return e.source
}

/**
 * Every MachineDB plant in use (or mapped by hand) with the plm2 plant it
 * maps to. A change saves only the plants touched (the server merges); a
 * hand mapping can be dropped so the default by plant name applies again.
 */
function PlantMapping({ data, plants }: { data: MachinesListing; plants: PlantCurrency[] }) {
  const qc = useQueryClient()
  const keys = useMemo(() => {
    const inUse = new Set(data.machines.map((m) => m.machinedb_plant).filter(Boolean) as string[])
    return Object.entries(data.plant_map)
      .filter(([k, v]) => inUse.has(k) || v.source === 'setting').map(([k]) => k).sort()
  }, [data])
  const unmappedKeys = keys.filter((k) => {
    const e = data.plant_map[k]
    return e.plant_id == null && e.source !== 'setting'
  })
  const [pick, setPick] = useState<Record<string, string>>({})
  useEffect(() => { setPick({}) }, [data.plant_map])
  const done = (msg: string) => () => {
    qc.invalidateQueries({ queryKey: ['cost-sheet', 'machines'] })
    toast.success(msg)
  }
  const save = useMutation({
    mutationFn: (m: Record<string, number | null>) => costSheetMachinesApi.setPlantMap(m),
    onSuccess: done('Plant mapping saved'),
    onError: (e) => toastError(e, 'Could not save the plant mapping'),
  })
  const reset = useMutation({
    mutationFn: (key: string) => costSheetMachinesApi.deletePlantMap(key),
    onSuccess: done('Mapping reset to the default'),
    onError: (e) => toastError(e, 'Could not reset the plant mapping'),
  })
  if (keys.length === 0) return null
  const current = (k: string) => (data.plant_map[k]?.plant_id == null ? '' : String(data.plant_map[k].plant_id))
  // touched and either different, or a default the user now confirms by hand
  const changed = Object.entries(pick).filter(([k, v]) =>
    v !== current(k) || data.plant_map[k]?.source !== 'setting')
  const plantLabel = (id: number | null) =>
    id == null ? 'Not mapped' : plants.find((p) => p.id === id)?.name ?? `Plant ${id}`
  return (
    <details open={unmappedKeys.length > 0 || undefined}
      className="rounded-lg border border-slate-700 bg-slate-800/40 px-4 py-3 text-sm">
      <summary className="cursor-pointer select-none text-slate-300">
        Plant mapping
        <span className="ml-2 text-xs text-slate-500">
          {keys.length} MachineDB plant{keys.length === 1 ? '' : 's'}
          {unmappedKeys.length ? `, ${unmappedKeys.length} without a plm2 plant` : ''}
        </span>
      </summary>
      {unmappedKeys.length > 0 && (
        <p data-testid="machinedb-unmapped" className="mt-2 text-amber-200">
          Machines of {unmappedKeys.join(', ')} have no plm2 plant, so costing cannot price them by plant.
          {data.can_sync ? ' Map them, or keep them unmapped on purpose.' : ' Sales or Finance can map them.'}
        </p>
      )}
      <div className="mt-2 grid gap-x-4 gap-y-2 sm:grid-cols-[max-content_minmax(12rem,max-content)_1fr]"
        data-testid="machinedb-plant-map">
        {keys.map((k) => {
          const e = data.plant_map[k]
          return (
            <div key={k} className="contents">
              <span className="self-center capitalize text-slate-300" id={`map-${k}`}>{k}</span>
              {data.can_sync ? (
                <select aria-labelledby={`map-${k}`} value={pick[k] ?? current(k)}
                  onChange={(ev) => setPick((p) => ({ ...p, [k]: ev.target.value }))}
                  className="rounded-md border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
                  <option value="">Not mapped</option>
                  {plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              ) : (
                <span className="self-center text-slate-200">{plantLabel(e.plant_id)}</span>
              )}
              <span className="flex items-center gap-2 self-center text-xs text-slate-500">
                {mapSource(e)}
                {data.can_sync && e.source === 'setting' && (
                  <button type="button" className={btnSm.ghost} disabled={reset.isPending}
                    onClick={() => reset.mutate(k)}
                    title="Drop the hand mapping; the default by plant name applies again">
                    Use default
                  </button>
                )}
              </span>
            </div>
          )
        })}
      </div>
      {data.can_sync && (
        <button type="button" className={`${btnSm.primary} mt-3`}
          disabled={save.isPending || changed.length === 0}
          onClick={() => save.mutate(Object.fromEntries(
            changed.map(([k, v]) => [k, v === '' ? null : Number(v)])))}>
          Save mapping
        </button>
      )}
    </details>
  )
}

// ---------------------------------------------------------------- table

function MachineTable({ data, versionId, editable, plantName }: {
  data: MachinesListing; versionId: number | null; editable: boolean
  plantName: (id: number | null) => string
}) {
  const table = useTableState()
  const cols: FilterColumnDef<CostSheetMachine>[] = useMemo(() => [
    { key: 'plant', label: 'Plant', kind: 'values', value: (m) => plantName(m.plant_id) },
    { key: 'name', label: 'Machine', kind: 'values', value: (m) => m.internal_name },
    { key: 'tonnage', label: 'Tonnage t', kind: 'number', value: (m) => m.clamping_force_t },
    { key: 'class', label: 'Class', kind: 'values', value: (m) => m.machine_class },
    { key: 'two_k', label: '2K type', kind: 'values', value: (m) => (m.two_k_type ? TWO_K[m.two_k_type] ?? m.two_k_type : '1K') },
    { key: 'status', label: 'Status', kind: 'values', value: machineStatus },
    { key: 'rate', label: 'Rate / h', kind: 'number', value: (m) => m.hourly_rate },
    { key: 'local', label: 'Local / h', kind: 'number', value: (m) => m.local_rate },
    { key: 'class_rate', label: 'Class rate / h', kind: 'number', value: (m) => m.class_rate },
  ], [plantName])
  // the local column only where a plant has a second currency (Silao: MXN)
  const dual = data.machines.some((m) => m.local_currency)
  const span = dual ? 9 : 8
  const colBy = Object.fromEntries(cols.map((c) => [c.key, c]))
  const shown = applyTableState(data.machines, cols, table.state)
  // Grouped by plant; the order inside a plant follows the sort.
  const groups = useMemo(() => {
    const g = new Map<string, CostSheetMachine[]>()
    for (const m of shown) {
      const k = plantName(m.plant_id)
      if (!g.has(k)) g.set(k, [])
      g.get(k)!.push(m)
    }
    return [...g.entries()].sort(([a], [b]) =>
      a === UNMAPPED ? 1 : b === UNMAPPED ? -1 : a.localeCompare(b))
  }, [shown, plantName])

  if (data.machines.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-700 px-6 py-8 text-center text-sm">
        <p className="text-slate-300">No machines synced yet.</p>
        <p className="mt-1 text-slate-500">
          {data.can_sync ? 'Sync from MachineDB to list the presses.' : 'Sales or Finance syncs them from MachineDB.'}
        </p>
      </div>
    )
  }
  const head = (key: string, right = false) => (
    <th key={key} aria-sort={ariaSort(table.state, key)}
      className={`px-3 py-2 font-medium whitespace-nowrap ${right ? 'text-right' : 'text-left'}`}>
      <ColumnHeader col={colBy[key]} rows={data.machines} cols={cols} state={table.state}
        onToggleSort={table.toggleSort} onFilter={table.setFilter} align={right ? 'right' : 'left'} />
    </th>
  )
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TableFilterBar count={table.activeCount} onClear={table.clearFilters}
          shown={shown.length} total={data.machines.length} />
        {versionId != null && (
          <a href={costSheetApi.exportUrl(versionId, 'csv', 'MachineRates')} download
            className="text-xs text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline">
            Machine rates as CSV
          </a>
        )}
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-700/80">
        <table className="w-full text-sm" data-testid="machinedb-table">
          <thead className="bg-slate-800/80 text-[11px] uppercase tracking-wide text-slate-400">
            <tr>
              {head('name')}{head('tonnage', true)}{head('class')}{head('two_k')}{head('status')}
              {head('rate', true)}{dual && head('local', true)}{head('class_rate', true)}{head('plant')}
            </tr>
          </thead>
          <tbody>
            {groups.length === 0 && (
              <tr><td colSpan={span} className="px-3 py-6 text-center text-slate-500">No machine matches the filters.</td></tr>
            )}
            {groups.map(([plant, rows]) => (
              <PlantGroup key={plant} plant={plant} rows={rows} versionId={versionId} editable={editable}
                dual={dual} currencies={data.currencies ?? []} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PlantGroup({ plant, rows, versionId, editable, dual, currencies }: {
  plant: string; rows: CostSheetMachine[]; versionId: number | null; editable: boolean
  dual: boolean; currencies: string[]
}) {
  const own = rows.filter((m) => m.hourly_rate != null).length
  return (
    <>
      <tr className="border-t border-slate-700 bg-slate-800/40">
        <th scope="rowgroup" colSpan={dual ? 9 : 8} className="px-3 py-1.5 text-left text-xs font-semibold text-slate-300">
          {plant}
          <span className="ml-2 font-normal text-slate-500">
            {rows.length} machine{rows.length === 1 ? '' : 's'}{own ? `, ${own} with an own rate` : ''}
          </span>
        </th>
      </tr>
      {rows.map((m) => (
        <tr key={m.id} data-testid={`machine-row-${m.id}`}
          className={`border-t border-slate-800 hover:bg-slate-800/40 ${machineStatus(m) === 'Active' ? '' : 'text-slate-500'}`}>
          <td className="px-3 py-1.5">
            <span className={machineStatus(m) === 'Active' ? 'text-slate-100' : ''}>{m.internal_name}</span>
            {(m.manufacturer || m.model) && (
              <span className="block text-[11px] text-slate-500">{[m.manufacturer, m.model].filter(Boolean).join(' ')}</span>
            )}
          </td>
          <td className="px-3 py-1.5 text-right tabular-nums">
            {m.clamping_force_t != null ? formatNumber(m.clamping_force_t, { max: 0 }) : '-'}
          </td>
          <td className="px-3 py-1.5 whitespace-nowrap">
            {m.machine_class ?? <span className="text-slate-600" title="No class band holds this tonnage">-</span>}
          </td>
          <td className="px-3 py-1.5 whitespace-nowrap text-slate-400">
            {m.two_k_type ? TWO_K[m.two_k_type] ?? m.two_k_type : '1K'}
          </td>
          <td className="px-3 py-1.5 whitespace-nowrap">
            <StatusPill m={m} />
          </td>
          <td className="px-3 py-1.5 text-right">
            <RateCell m={m} versionId={versionId} editable={editable} currencies={currencies} />
          </td>
          {dual && (
            <td className="px-3 py-1.5 text-right">
              <LocalRateCell m={m} versionId={versionId} editable={editable} />
            </td>
          )}
          <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
            {m.class_rate != null ? formatMoney(m.class_rate, m.class_rate_currency) : '-'}
          </td>
          <td className="px-3 py-1.5 whitespace-nowrap text-xs text-slate-500">{m.machinedb_plant ?? '-'}</td>
        </tr>
      ))}
    </>
  )
}

function StatusPill({ m }: { m: CostSheetMachine }) {
  const s = machineStatus(m)
  const cls = s === 'Active' ? 'bg-emerald-500/15 text-emerald-300'
    : s === 'Scrapped' ? 'bg-slate-700 text-slate-300' : 'bg-amber-500/15 text-amber-300'
  const title = s === 'Scrapped' && m.planned_scrap_from ? `Scrapped from ${m.planned_scrap_from}`
    : s === 'Retired' ? 'MachineDB no longer lists this machine' : undefined
  return <span title={title} className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{s}</span>
}

/** "calculated" under the side that was not typed, like the rates tab. */
function Calculated({ from }: { from: string }) {
  return (
    <span className="block text-[10px] text-slate-500"
      title={`Calculated from the ${from} rate at this version's exchange rate. The ${from} number is kept as typed.`}>
      calculated
    </span>
  )
}

function useRateSave(m: CostSheetMachine, versionId: number | null, reset: () => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Omit<Parameters<typeof costSheetMachinesApi.setRate>[1], 'version_id'>) =>
      costSheetMachinesApi.setRate(m.id, { version_id: versionId as number, ...body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost-sheet', 'machines'] })
      qc.invalidateQueries({ queryKey: ['cost-sheet', 'diff', versionId] })
    },
    onError: (e) => {
      reset()
      toastError(e, 'Could not save the machine rate')
    },
  })
}

/**
 * A typed rate, read like every number input (lib/format readNumberInput):
 * empty = null, "1,500" = 1500, "4,5" refused as ambiguous rather than
 * guessed (re-check walk P2-3). A refusal carries the reason to show.
 */
function parseRate(value: string): { value: number | null } | { refused: string } {
  const r = readNumberInput(value)
  if (r.error === 'ambiguous') return { refused: NUMBER_INPUT_HINT }
  if (r.error) return { refused: NUMBER_INPUT_INVALID }
  if (r.value !== null && r.value < 0) return { refused: 'A rate is a number of 0 or more' }
  return { value: r.value }
}

/** A saved rate as edit text: 2 decimals like the Rates tab ("47.50"), more
 * only when the stored number has them, so a blur never rounds it. */
function rateEditText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return ''
  return Number(v.toFixed(2)) === v ? v.toFixed(2) : String(v)
}

/** The inline reason a typed rate was refused (the field is back on the saved value). */
function RateRefusal({ id, text }: { id: string; text: string | null }) {
  if (!text) return null
  return (
    <span id={id} role="alert" className="mt-0.5 block max-w-[14rem] text-left text-[11px] leading-tight text-amber-300">
      {text}
    </span>
  )
}

const INPUT = 'w-24 rounded border border-slate-600 bg-slate-900 px-2 py-1 text-right text-sm tabular-nums text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40 disabled:opacity-60'

/**
 * The machine's own rate and its currency. A new rate defaults to the
 * currency of the machine's plant; an unmapped machine has none, so the
 * currency has to be chosen before the rate is saved.
 */
function RateCell({ m, versionId, editable, currencies }: {
  m: CostSheetMachine; versionId: number | null; editable: boolean; currencies: string[]
}) {
  const shown = rateEditText(m.hourly_rate)
  const [value, setValue] = useState(shown)
  const [refused, setRefused] = useState<string | null>(null)
  const msgId = useId()
  const defaultCur = m.currency ?? m.plant_currency ?? ''
  const [cur, setCur] = useState(defaultCur)
  useEffect(() => { setValue(shown) }, [shown])
  useEffect(() => { setCur(defaultCur) }, [defaultCur])
  const save = useRateSave(m, versionId, () => { setValue(shown); setCur(defaultCur) })
  if (!editable || versionId == null) {
    return m.hourly_rate != null
      ? (
        <span className="tabular-nums text-slate-100">
          {formatMoney(m.hourly_rate, m.currency)}
          {m.entered_in === 'local' && m.local_currency && <Calculated from={m.local_currency} />}
        </span>
      )
      : <span className="text-slate-600" title="The class rate applies">-</span>
  }
  // the currency only goes along when it is not what the server defaults to
  const withCurrency = (c: string) => (c && c !== (m.currency ?? m.plant_currency) ? { currency: c } : {})
  const commit = () => {
    if (value === shown && cur === defaultCur) return
    const read = parseRate(value)
    if ('refused' in read) {
      setRefused(`"${value.trim()}" not saved. ${read.refused}`)
      setValue(shown)
      return
    }
    setRefused(null)
    const next = read.value
    if (next === m.hourly_rate && cur === defaultCur) return
    if (next !== null && !cur) {
      toast.error(`Choose the currency of ${m.internal_name}'s rate first: it is not mapped to a plant`)
      return
    }
    save.mutate({ hourly_rate: next, ...withCurrency(cur) })
  }
  const options = cur && !currencies.includes(cur) ? [cur, ...currencies] : currencies
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>
        <input value={value} inputMode="decimal" placeholder="Class rate"
          aria-label={`Hourly rate of ${m.internal_name}`}
          aria-describedby={refused ? msgId : undefined}
          disabled={save.isPending}
          onChange={(e) => { setValue(e.target.value); setRefused(null) }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            if (e.key === 'Escape') setValue(shown)
          }}
          className={INPUT} />
        {m.entered_in === 'local' && m.local_currency && <Calculated from={m.local_currency} />}
        <RateRefusal id={msgId} text={refused} />
      </span>
      <select value={cur} aria-label={`Currency of the rate of ${m.internal_name}`}
        disabled={save.isPending}
        onChange={(e) => {
          const c = e.target.value
          setCur(c)
          // an existing rate moves to the new currency right away
          if (m.hourly_rate != null && c && c !== m.currency) {
            save.mutate({ hourly_rate: m.hourly_rate, currency: c })
          }
        }}
        className={`w-[4.5rem] rounded border bg-slate-900 px-1 py-1 text-xs text-slate-200 focus:border-sky-500 focus:outline-none ${cur ? 'border-slate-600' : 'border-amber-500/60'}`}>
        {!cur && <option value="">Currency</option>}
        {options.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </span>
  )
}

/** The rate in the plant's local currency (Silao: MXN). Typed here, the
 * number is kept and the rate in the quote currency is calculated. */
function LocalRateCell({ m, versionId, editable }: {
  m: CostSheetMachine; versionId: number | null; editable: boolean
}) {
  const shown = rateEditText(m.local_rate)
  const [value, setValue] = useState(shown)
  const [refused, setRefused] = useState<string | null>(null)
  const msgId = useId()
  // a typed local rate waiting for "switch the rate to the quote currency first"
  const [ask, setAsk] = useState<number | null>(null)
  useEffect(() => { setValue(shown) }, [shown])
  const save = useRateSave(m, versionId, () => setValue(shown))
  if (!m.local_currency) return <span className="text-slate-700">-</span>
  // the local rate converts into the plant's quote currency only
  const offQuote = !!(m.currency && m.plant_currency && m.currency !== m.plant_currency)
  const hint = m.entered_in === 'quote' && m.currency ? <Calculated from={m.currency} /> : null
  if (!editable || versionId == null) {
    return m.local_rate != null
      ? <span className="tabular-nums text-slate-300">{formatMoney(m.local_rate, m.local_currency)}{hint}</span>
      : <span className="text-slate-600">-</span>
  }
  const commit = () => {
    if (value === shown) return
    const read = parseRate(value)
    if ('refused' in read) {
      setRefused(`"${value.trim()}" not saved. ${read.refused}`)
      setValue(shown)
      return
    }
    setRefused(null)
    const next = read.value
    if (next === m.local_rate) return
    if (next !== null && offQuote) { setAsk(next); return }
    save.mutate({ entered_rate: next, entered_currency: m.local_currency })
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>
        <input value={value} inputMode="decimal" placeholder="-"
          aria-label={`Hourly rate of ${m.internal_name} in ${m.local_currency}`}
          aria-describedby={refused ? msgId : undefined}
          disabled={save.isPending}
          onChange={(e) => { setValue(e.target.value); setRefused(null) }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            if (e.key === 'Escape') setValue(shown)
          }}
          className={INPUT} />
        {hint}
        <RateRefusal id={msgId} text={refused} />
      </span>
      <span className="w-8 text-left text-xs text-slate-500">{m.local_currency}</span>
      <ConfirmDialog open={ask !== null} title={`Switch this rate to ${m.plant_currency}?`}
        body={`${m.internal_name}'s rate is in ${m.currency}, not its plant's quote currency ${m.plant_currency}. `
          + `A rate typed in ${m.local_currency} is converted into ${m.plant_currency} only. Switch the rate to `
          + `${m.plant_currency} and save the ${m.local_currency} rate? The ${m.currency} number is replaced.`}
        confirmLabel={`Switch to ${m.plant_currency}`}
        onConfirm={() => {
          if (ask !== null) {
            save.mutate({ entered_rate: ask, entered_currency: m.local_currency,
              currency: m.plant_currency as string })
          }
          setAsk(null)
        }}
        onClose={() => { setAsk(null); setValue(shown) }} />
    </span>
  )
}

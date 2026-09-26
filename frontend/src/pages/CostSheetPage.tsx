/**
 * CostSheetPage - Finance's versioned rates (spec §15 / §15a).
 *
 * Everyone reads; Finance (or an admin) edits drafts in place and publishes
 * them with a valid-from date. Tabs: Positions, Machines, Sampling, Overheads.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { costSheetApi } from '../api/costSheet'
import { apiErrorMessage, toastError } from '../lib/apiError'
import { formatCalendarDate, formatDateTime, todayIso } from '../lib/format'
import { LoadingSkeleton } from '../components/common/LoadingSkeleton'
import { buttonClass } from '../components/common/buttonStyles'
import ConfirmModal from '../components/common/ConfirmModal'
import SectionTable from '../components/costSheet/SectionTable'
import PublishDialog from '../components/costSheet/PublishDialog'
import DiffPanel, { diffCount } from '../components/costSheet/DiffPanel'
import StaleBanner from '../components/costSheet/StaleBanner'
import MachineClassStrip from '../components/costSheet/MachineClassStrip'
import PlantCurrencies from '../components/costSheet/PlantCurrencies'
import {
  SECTION_BLURB, SECTION_EXPORT, SECTION_LABELS, sortRows, type SheetContext,
} from '../components/costSheet/columns'
import type {
  CostSheetRow, CostSheetSection, CostSheetVersionDetail, CostSheetVersionSummary,
} from '../types/costSheet'

const SECTIONS: CostSheetSection[] = ['rates', 'machines', 'sampling', 'overheads']
const ROWS_KEY: Record<CostSheetSection, keyof CostSheetVersionDetail> = {
  rates: 'rates', machines: 'machine_rates', sampling: 'sampling_rates', overheads: 'overheads',
}

function validityText(v: CostSheetVersionSummary): string {
  if (v.status === 'draft') {
    return v.valid_from ? `Draft, planned from ${formatCalendarDate(v.valid_from)}` : 'Draft, not yet valid'
  }
  return v.valid_to
    ? `Valid ${formatCalendarDate(v.valid_from)} to ${formatCalendarDate(v.valid_to)}`
    : `Valid from ${formatCalendarDate(v.valid_from)}, open-ended`
}

function StatusPill({ v, currentId }: { v: CostSheetVersionSummary; currentId: number | null }) {
  if (v.status === 'draft') {
    return <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-300">Draft</span>
  }
  if (v.id === currentId) {
    return <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-300">Current</span>
  }
  const future = v.valid_from && v.valid_from.slice(0, 10) > todayIso()
  return future
    ? <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs font-medium text-sky-300">Upcoming</span>
    : <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs font-medium text-slate-300">Superseded</span>
}

const BTN = 'rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50'

export default function CostSheetPage() {
  const qc = useQueryClient()
  const overview = useQuery({ queryKey: ['cost-sheet'], queryFn: costSheetApi.overview })
  const ov = overview.data
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [tab, setTab] = useState<CostSheetSection>('rates')
  const [showDiff, setShowDiff] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [discardOpen, setDiscardOpen] = useState(false)
  const [editingCycle, setEditingCycle] = useState(false)
  const [cycle, setCycle] = useState('')

  // Default selection: an editor lands on the open draft, everyone else on
  // the version valid today.
  useEffect(() => {
    if (!ov || selectedId !== null) return
    const pick = (ov.can_edit && ov.draft_version_id) || ov.current_version_id || ov.versions[0]?.id || null
    setSelectedId(pick)
  }, [ov, selectedId])

  const version = useQuery({
    queryKey: ['cost-sheet', 'version', selectedId],
    queryFn: () => costSheetApi.version(selectedId as number),
    enabled: selectedId !== null,
  })
  const v = version.data
  const summary = ov?.versions.find((x) => x.id === selectedId)
  const isDraft = v?.status === 'draft'
  const editable = !!(ov?.can_edit && isDraft)

  const diff = useQuery({
    queryKey: ['cost-sheet', 'diff', selectedId],
    queryFn: () => costSheetApi.diff(selectedId as number),
    enabled: selectedId !== null && (showDiff || publishOpen),
  })

  const ctx: SheetContext = useMemo(() => ({
    departments: ov?.departments ?? [],
    plants: ov?.plants ?? [],
    machineClasses: ov?.machine_classes ?? [],
    currencies: ov?.currencies ?? ['EUR'],
  }), [ov])

  const latestPublished = useMemo(() => {
    const pub = (ov?.versions ?? []).filter((x) => x.status === 'published' && x.valid_from)
    return pub.sort((a, b) => (a.valid_from! < b.valid_from! ? 1 : -1))[0] ?? null
  }, [ov])

  const onDetail = (d: CostSheetVersionDetail) => {
    qc.setQueryData(['cost-sheet', 'version', d.id], d)
    qc.invalidateQueries({ queryKey: ['cost-sheet', 'diff', d.id] })
  }
  const fail = (e: unknown) => { toastError(e, 'Could not save the cost sheet') }

  const rowMut = useMutation({
    mutationFn: (a: { kind: 'add' | 'update' | 'delete'; rowId?: number; row?: CostSheetRow }) => {
      const id = selectedId as number
      if (a.kind === 'add') return costSheetApi.addRow(id, tab, a.row ?? {})
      if (a.kind === 'update') return costSheetApi.updateRow(id, tab, a.rowId as number, a.row ?? {})
      return costSheetApi.deleteRow(id, tab, a.rowId as number)
    },
    onSuccess: onDetail,
    onError: (e) => {
      fail(e)
      // put the cell back to what the server holds
      qc.invalidateQueries({ queryKey: ['cost-sheet', 'version', selectedId] })
    },
  })

  const draftMut = useMutation({
    mutationFn: () => costSheetApi.createDraft(),
    onSuccess: (d) => {
      onDetail(d)
      qc.invalidateQueries({ queryKey: ['cost-sheet'], exact: true })
      setSelectedId(d.id)
      // Say what it was really copied from: the latest published version,
      // which may be one valid only from a future date, not "the current rates".
      const base = ov?.versions.find((x) => x.id === d.based_on_version_id)
      toast.success(base
        ? `Draft version ${d.version} started from v${base.version}`
        : `Draft version ${d.version} started empty`)
    },
    onError: fail,
  })

  const publishMut = useMutation({
    mutationFn: (b: { validFrom: string; note: string; confirmBackdated: boolean }) =>
      costSheetApi.publish(selectedId as number, {
        valid_from: b.validFrom, note: b.note || null, confirm_backdated: b.confirmBackdated,
      }),
    onSuccess: (d) => {
      onDetail(d)
      qc.invalidateQueries({ queryKey: ['cost-sheet'] })
      setPublishOpen(false)
      const vf = d.valid_from ?? ''
      toast.success(vf > todayIso()
        ? `Version ${d.version} published. It takes over on ${formatCalendarDate(vf)}; until then the current version stays in use.`
        : `Version ${d.version} published and in use from ${formatCalendarDate(vf)}`)
    },
    onError: fail,
  })

  const discardMut = useMutation({
    mutationFn: () => costSheetApi.deleteDraft(selectedId as number),
    onSuccess: () => {
      setDiscardOpen(false)
      setSelectedId(ov?.current_version_id ?? ov?.versions.find((x) => x.status === 'published')?.id ?? null)
      qc.invalidateQueries({ queryKey: ['cost-sheet'] })
      toast.success('Draft discarded')
    },
    onError: fail,
  })

  const cycleMut = useMutation({
    mutationFn: (m: number) => costSheetApi.setReviewMonths(m),
    onSuccess: () => {
      setEditingCycle(false)
      qc.invalidateQueries({ queryKey: ['cost-sheet'], exact: true })
    },
    onError: fail,
  })

  const renameClass = async (id: number, name: string) => {
    try {
      await costSheetApi.updateMachineClass(id, { name })
      qc.invalidateQueries({ queryKey: ['cost-sheet'] })
      return true
    } catch (e) {
      fail(e)
      return false
    }
  }

  const plantCurrencyMut = useMutation({
    mutationFn: (a: { plantId: number; currency: string }) => costSheetApi.setPlantCurrency(a.plantId, a.currency),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cost-sheet'], exact: true }),
    onError: fail,
  })

  const addClass = async (body: { name: string; tonnage_min: number | null; tonnage_max: number | null }) => {
    try {
      await costSheetApi.addMachineClass(body)
      qc.invalidateQueries({ queryKey: ['cost-sheet'], exact: true })
      return true
    } catch (e) {
      fail(e)
      return false
    }
  }

  if (overview.isLoading) {
    return (
      <div className="mx-auto max-w-7xl p-6" aria-busy="true">
        <h1 className="px-6 text-2xl font-semibold text-slate-100">Cost sheet</h1>
        <span className="sr-only">Loading the cost sheet</span>
        <LoadingSkeleton count={4} />
      </div>
    )
  }
  if (overview.isError || !ov) {
    return <div className="mx-auto max-w-7xl p-6 text-red-300">{apiErrorMessage(overview.error, 'Could not load the cost sheet')}</div>
  }

  const rows = v ? sortRows(v[ROWS_KEY[tab]] as unknown as CostSheetRow[], ctx) : []
  const counts = v ? Object.fromEntries(SECTIONS.map((s) => [s, (v[ROWS_KEY[s]] as unknown[]).length])) : {}

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Cost sheet</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Hourly rates per position, machine and sampling prices and personnel overhead, maintained by Finance.
            Costing and the P&amp;L read the version valid on the day.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span>Review every</span>
          {editingCycle ? (
            <form className="flex items-center gap-1.5" onSubmit={(e) => {
              e.preventDefault()
              const n = Number(cycle)
              if (Number.isInteger(n) && n >= 1 && n <= 120) cycleMut.mutate(n)
              else toast.error('The review cycle is 1 to 120 months')
            }}>
              <input autoFocus aria-label="Review cycle in months" value={cycle} inputMode="numeric"
                     onChange={(e) => setCycle(e.target.value)}
                     className="w-14 rounded border border-slate-600 bg-slate-900 px-2 py-1 text-right text-slate-100 focus:border-sky-500 focus:outline-none" />
              <span>months</span>
              <button type="submit" className="rounded px-2 py-1 text-sky-300 hover:bg-sky-500/10">Save</button>
              <button type="button" onClick={() => setEditingCycle(false)} className="px-1 text-slate-500 hover:text-slate-300">Cancel</button>
            </form>
          ) : (
            <>
              <span className="font-medium text-slate-200">{ov.stale.review_months} months</span>
              {ov.can_edit && (
                <button type="button" onClick={() => { setCycle(String(ov.stale.review_months)); setEditingCycle(true) }}
                        className="rounded px-1.5 py-0.5 text-sky-300 hover:bg-sky-500/10">Change</button>
              )}
            </>
          )}
        </div>
      </div>

      <StaleBanner stale={ov.stale} canEdit={ov.can_edit} />
      <PlantCurrencies plants={ov.plants} currencies={ov.currencies} canEdit={ov.can_edit}
                       onSet={(plantId, currency) => plantCurrencyMut.mutate({ plantId, currency })} />

      {/* Version bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-xs uppercase tracking-wide text-slate-500">Version</span>
          <select value={selectedId ?? ''} onChange={(e) => { setSelectedId(Number(e.target.value)); setShowDiff(false) }}
                  className="rounded-md border border-slate-600 bg-slate-900 px-2 py-1.5 text-slate-100 focus:border-sky-500 focus:outline-none"
                  disabled={ov.versions.length === 0}>
            {ov.versions.length === 0 && <option value="">No versions yet</option>}
            {ov.versions.map((x) => (
              <option key={x.id} value={x.id}>
                v{x.version} · {x.status === 'draft' ? 'draft' : x.valid_to
                  ? `${formatCalendarDate(x.valid_from)} to ${formatCalendarDate(x.valid_to)}`
                  : `from ${formatCalendarDate(x.valid_from)}`}
              </option>
            ))}
          </select>
        </label>
        {summary && (
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
            <StatusPill v={summary} currentId={ov.current_version_id} />
            <span className="text-slate-300">{validityText(summary)}</span>
            {summary.note && <span className="truncate text-slate-500" title={summary.note}>· {summary.note}</span>}
            {summary.published_at && (
              <span className="text-xs text-slate-500">published {formatDateTime(summary.published_at)}</span>
            )}
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {selectedId !== null && (
            <button type="button" onClick={() => setShowDiff((s) => !s)} aria-pressed={showDiff}
                    className={`${BTN} ${showDiff ? 'bg-slate-700 text-slate-100' : 'text-slate-300 hover:bg-slate-700/60'}`}>
              {showDiff ? 'Hide changes' : 'Changes vs previous'}
            </button>
          )}
          {selectedId !== null && (
            <span className="flex items-center overflow-hidden rounded-md border border-slate-600">
              <a href={costSheetApi.exportUrl(selectedId, 'xlsx')} download
                 className="px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700/60">Export XLSX</a>
              <a href={costSheetApi.exportUrl(selectedId, 'csv', SECTION_EXPORT[tab])} download
                 title={`CSV of the ${SECTION_LABELS[tab]} tab`}
                 className="border-l border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700/60">CSV</a>
            </span>
          )}
          {ov.can_edit && ov.draft_version_id === null && (
            <button type="button" onClick={() => draftMut.mutate()} disabled={draftMut.isPending}
                    className={buttonClass('primary')}>
              New draft
            </button>
          )}
          {ov.can_edit && ov.draft_version_id !== null && !isDraft && (
            <button type="button" onClick={() => { setSelectedId(ov.draft_version_id); setShowDiff(false) }}
                    className={`${BTN} text-amber-300 hover:bg-amber-500/10`}>
              Open draft
            </button>
          )}
          {editable && (
            <>
              <button type="button" onClick={() => setDiscardOpen(true)}
                      className={`${BTN} text-slate-400 hover:bg-red-500/10 hover:text-red-300`}>
                Discard draft
              </button>
              <button type="button" onClick={() => setPublishOpen(true)}
                      className={buttonClass('primary')}>
                Publish version
              </button>
            </>
          )}
        </div>
      </div>

      {showDiff && diff.data && <DiffPanel diff={diff.data} ctx={ctx} />}

      {ov.versions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-700 px-6 py-12 text-center">
          <p className="text-slate-300">No cost sheet yet.</p>
          <p className="mt-1 text-sm text-slate-500">
            {ov.can_edit ? 'Start a draft, enter the rates and publish it.' : 'Finance has not published a cost sheet yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Tabs */}
          <div role="tablist" aria-label="Cost sheet parts" className="flex gap-1 border-b border-slate-700">
            {SECTIONS.map((s) => (
              <button key={s} role="tab" type="button" aria-selected={tab === s} onClick={() => setTab(s)}
                      className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
                        tab === s ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
                {SECTION_LABELS[s]}
                {v && <span className="ml-1.5 text-xs text-slate-500">{counts[s]}</span>}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="max-w-3xl text-sm text-slate-500">{SECTION_BLURB[tab]}</p>
            {v && !isDraft && ov.can_edit && (
              <p className="text-xs text-slate-500">Published versions are frozen. Start a draft to change rates.</p>
            )}
          </div>
          {(tab === 'machines' || tab === 'sampling') && (
            <MachineClassStrip classes={ov.machine_classes} canEdit={ov.can_edit} onAdd={addClass}
                               onRename={renameClass} />
          )}
          {version.isLoading ? (
            <div aria-busy="true"><span className="sr-only">Loading version</span><LoadingSkeleton count={3} /></div>
          ) : version.isError ? (
            <div role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-6 text-sm text-red-200">
              <p className="font-medium">This version could not be loaded.</p>
              <p className="mt-1 text-red-200/80">{apiErrorMessage(version.error, 'The server refused the request.')}</p>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => version.refetch()}
                        className={`${BTN} bg-slate-700 text-slate-100 hover:bg-slate-600`}>Try again</button>
                {ov.can_edit && summary?.status === 'draft' && (
                  <button type="button" onClick={() => setDiscardOpen(true)}
                          className={`${BTN} bg-red-600 text-white hover:bg-red-500`}>Discard draft</button>
                )}
              </div>
            </div>
          ) : v ? (
            <SectionTable
              section={tab}
              rows={rows}
              ctx={ctx}
              editable={editable}
              busy={rowMut.isPending}
              onUpdate={(rowId, changes) => rowMut.mutate({ kind: 'update', rowId, row: changes })}
              onDelete={(rowId) => rowMut.mutate({ kind: 'delete', rowId })}
              onAdd={async (row) => {
                try {
                  await rowMut.mutateAsync({ kind: 'add', row })
                  return true
                } catch {
                  return false
                }
              }}
            />
          ) : null}
        </div>
      )}

      {v && isDraft && (
        <PublishDialog
          open={publishOpen}
          version={v.version}
          defaultValidFrom={v.valid_from}
          defaultNote={v.note}
          latestValidFrom={latestPublished?.valid_from ?? null}
          latestVersion={latestPublished?.version ?? null}
          changeCount={diffCount(diff.data)}
          busy={publishMut.isPending}
          onCancel={() => setPublishOpen(false)}
          onPublish={(validFrom, note, confirmBackdated) => publishMut.mutate({ validFrom, note, confirmBackdated })}
        />
      )}
      <ConfirmModal
        isOpen={discardOpen}
        title={`Discard draft version ${v?.version ?? summary?.version ?? ''}?`}
        message="All changes in this draft are lost. Published versions are not touched."
        confirmText="Discard draft"
        isDangerous
        isLoading={discardMut.isPending}
        onConfirm={() => discardMut.mutate()}
        onCancel={() => setDiscardOpen(false)}
      />
    </div>
  )
}

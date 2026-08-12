/**
 * Stage 8 — how the work is actually going, department by department.
 *
 * The scheduling plan above says how the change reaches the line. This says
 * whether it is getting there: what each department has booked, what it last
 * reported, and whether anybody has taken a flagged risk somewhere. Three
 * records, three different desks, one block per department so that nobody has
 * to correlate three lists in their head.
 *
 * Scoped like the costing and assessment boards: an ordinary member gets their
 * own department's block and nothing else; PM, Sales, the change lead and
 * admins see every block. Escalations are not a secret inside a block — anyone
 * who may see the block sees them — but only Sales (with the lead and admins)
 * raises and settles one.
 *
 * Writes are open only while the change sits at `in_implementation`; before and
 * after, the card is the record of what happened.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import type {
  CostPosition, ImplBooking, ImplDepartmentState, ImplEscalation,
  ImplEscalationDirection, ImplReport,
} from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const onDay = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

/** 12 h, not 12.0 h; 12.5 h stays 12.5 h. */
const hoursText = (n: number) => String(Math.round(n * 100) / 100)

const DIRECTIONS: ImplEscalationDirection[] = ['customer', 'internal']

const fieldCls =
  'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

/**
 * What the outside world costs in time, taken from the favourite offer of each
 * external position — the same rule the costing board uses to decide which
 * vendor counts. One line under the header, because implementation timing is
 * argued against these numbers and nobody should have to open another tab.
 */
export function vendorLeadTimeLine(positions: CostPosition[]): string | null {
  const parts = positions
    .filter((p) => p.kind === 'external' && p.pricing === 'quote')
    .map((p) => {
      const fav = (p.offers ?? []).find((o) => o.favorite)
      if (!fav || fav.lead_time_days == null) return null
      const unit = t(`costpos.unitShort.${fav.lead_time_unit ?? 'calendar_days'}`)
      return `${p.label} — ${fav.lead_time_days} ${unit} (${fav.vendor_name})`
    })
    .filter((s): s is string => s !== null)
  return parts.length > 0 ? `${t('impl2.vendorLeadTimes')}: ${parts.join(' · ')}` : null
}

function EscalationList({ items, changeId, editable, canEscalate, testPrefix }: {
  items: ImplEscalation[]
  changeId: number
  editable: boolean
  canEscalate: boolean
  testPrefix: string
}) {
  const qc = useQueryClient()
  const [resolving, setResolving] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const resolve = useMutation({
    mutationFn: (vars: { id: number; note: string }) =>
      changesApi.resolveImplEscalation(changeId, vars.id, vars.note.trim()),
    onSuccess: () => {
      setResolving(null); setNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-escalations'] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-state'] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not resolve the escalation'),
  })

  if (items.length === 0) {
    return <p className="text-xs text-slate-500">{t('impl2.noEscalations')}</p>
  }
  return (
    <ul className="space-y-1">
      {items.map((e) => (
        <li key={e.id} data-testid={`${testPrefix}-${e.id}`}
          className={`rounded border px-2 py-1 text-sm ${
            e.resolved_at
              ? 'border-slate-700 bg-slate-900/40 text-slate-400'
              : 'border-amber-800 bg-amber-950/30 text-amber-100'}`}>
          <span className="flex items-start gap-2">
            <span data-testid={`impl-escalation-direction-${e.id}`}
              className="flex-shrink-0 rounded bg-slate-800/80 px-1.5 py-0 text-[10px] leading-tight font-semibold">
              {t(`impl2.direction.${e.direction}`)}
            </span>
            <span className="min-w-0 flex-1">
              <span className={e.resolved_at ? 'line-through' : ''}>{e.note}</span>
              <span className="block text-xs opacity-70">
                {e.created_by_name ?? '—'}
                {e.created_at ? ` · ${onDay(e.created_at)}` : ''}
              </span>
              <span data-testid={`impl-escalation-state-${e.id}`}
                className="block text-xs opacity-70">
                {e.resolved_at
                  ? t('impl2.escalationResolved').replace('{d}', onDay(e.resolved_at))
                  : t('impl2.escalationOpen')}
              </span>
              {e.resolved_at && e.resolution_note && (
                <span className="block text-xs opacity-70">{e.resolution_note}</span>
              )}
              {resolving === e.id && (
                <span className="mt-1 flex flex-wrap items-center gap-2">
                  <textarea rows={2} value={note} onChange={(ev) => setNote(ev.target.value)}
                    data-testid={`impl-escalation-resolution-${e.id}`}
                    aria-label={t('impl2.resolutionNote')}
                    placeholder={t('impl2.resolutionNote')}
                    className={`flex-1 min-w-[12rem] ${fieldCls}`} />
                  <button type="button" data-testid={`impl-escalation-resolve-confirm-${e.id}`}
                    disabled={!note.trim() || resolve.isPending}
                    onClick={() => resolve.mutate({ id: e.id, note })}
                    className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
                    {t('impl2.resolve')}
                  </button>
                  <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
                    onClick={() => { setResolving(null); setNote('') }}>
                    {t('common.cancel')}
                  </button>
                </span>
              )}
            </span>
            {!e.resolved_at && canEscalate && editable && resolving !== e.id && (
              <button type="button" data-testid={`impl-escalation-resolve-${e.id}`}
                onClick={() => { setResolving(e.id); setNote('') }}
                className="flex-shrink-0 text-xs underline decoration-dotted">
                {t('impl2.resolve')}
              </button>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function DepartmentBlock({
  changeId, state, name, isMine, editable, canEscalate,
  bookings, reports, escalations,
}: {
  changeId: number
  state: ImplDepartmentState
  name: string
  isMine: boolean
  editable: boolean
  canEscalate: boolean
  bookings: ImplBooking[]
  reports: ImplReport[]
  escalations: ImplEscalation[]
}) {
  const qc = useQueryClient()
  const { userId } = useAuth()
  const id = state.department_id

  const [hours, setHours] = useState('')
  const [bookingNote, setBookingNote] = useState('')
  const [reportNote, setReportNote] = useState('')
  const [atRisk, setAtRisk] = useState(false)
  const [riskNote, setRiskNote] = useState('')
  const [escalating, setEscalating] = useState(false)
  const [direction, setDirection] = useState<ImplEscalationDirection>('customer')
  const [escalationNote, setEscalationNote] = useState('')

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-state'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-bookings'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-reports'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-escalations'] })
  }

  const addBooking = useMutation({
    mutationFn: () => changesApi.addImplBooking(changeId, {
      department_id: id, hours: Number(hours),
      ...(bookingNote.trim() !== '' ? { note: bookingNote.trim() } : {}),
    }),
    onSuccess: () => { setHours(''); setBookingNote(''); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not book the time'),
  })
  const removeBooking = useMutation({
    mutationFn: (bookingId: number) => changesApi.deleteImplBooking(changeId, bookingId),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not delete the booking'),
  })
  const addReport = useMutation({
    mutationFn: () => changesApi.addImplReport(changeId, {
      department_id: id, note: reportNote.trim(), at_risk: atRisk,
      ...(atRisk && riskNote.trim() !== '' ? { risk_note: riskNote.trim() } : {}),
    }),
    onSuccess: () => { setReportNote(''); setAtRisk(false); setRiskNote(''); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the report'),
  })
  // The escalation answers the newest at-risk report of this department — that
  // is also the only link the block has to find its own escalations again.
  const riskReport = reports.find((r) => r.at_risk)
  const addEscalation = useMutation({
    mutationFn: () => changesApi.addImplEscalation(changeId, {
      direction, note: escalationNote.trim(),
      ...(riskReport ? { report_id: riskReport.id } : {}),
    }),
    onSuccess: () => { setEscalating(false); setEscalationNote(''); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not escalate'),
  })

  const hoursValue = Number(hours)
  const hoursOk = hours.trim() !== '' && !Number.isNaN(hoursValue) && hoursValue > 0
  // A red flag with no explanation is not a report — it is a rumour.
  const reportOk = reportNote.trim() !== '' && (!atRisk || riskNote.trim() !== '')
  const openEscalation = escalations.some((e) => !e.resolved_at)
  const mayWrite = editable && isMine

  return (
    <section data-testid={`impl-block-${id}`}
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-3 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-100 font-medium">{name}</span>
        {isMine && (
          <span className="rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[10px] leading-tight">
            {t('costing.yourBucket')}
          </span>
        )}
        {/* The cadence, in one chip: either this department has said something
            recently enough, or it owes a word. */}
        <span data-testid={`impl-cadence-${id}`}
          title={state.last_report_at
            ? t('impl2.lastReport').replace('{d}', onDay(state.last_report_at))
            : undefined}
          className={`rounded px-1.5 py-0 text-[10px] leading-tight font-medium ${
            state.owes_report
              ? 'bg-amber-900/70 text-amber-200'
              : 'bg-emerald-900/70 text-emerald-200'}`}>
          {state.owes_report ? t('impl2.reportDue') : t('impl2.reported')}
        </span>
        {state.at_risk_open && (
          <span data-testid={`impl-atrisk-${id}`}
            className="rounded bg-red-900/80 text-red-100 px-1.5 py-0 text-[10px] leading-tight font-semibold">
            {t('impl2.atRisk')}
          </span>
        )}
        <span data-testid={`impl-hours-${id}`} className="ml-auto text-xs text-slate-300 tabular-nums">
          {t('impl2.bookedHours').replace('{n}', hoursText(state.booked_hours))}
        </span>
      </div>

      {/* Booked time */}
      <div className="space-y-1">
        <p className="text-xs font-medium text-slate-400">{t('impl2.booked')}</p>
        {bookings.length === 0 ? (
          <p className="text-xs text-slate-500">{t('impl2.noBookings')}</p>
        ) : (
          <ul className="space-y-0.5">
            {bookings.map((b) => (
              <li key={b.id} data-testid={`impl-booking-${b.id}`}
                className="flex items-baseline gap-2 text-xs text-slate-300">
                <span className="tabular-nums text-slate-100">{hoursText(b.hours)} h</span>
                <span className="min-w-0 flex-1">{b.note}</span>
                <span className="opacity-70">
                  {b.created_by_name ?? '—'}{b.created_at ? ` · ${onDay(b.created_at)}` : ''}
                </span>
                {/* Only your own booking is yours to take back. */}
                {mayWrite && userId != null && b.created_by === userId && (
                  <button type="button" data-testid={`impl-booking-delete-${b.id}`}
                    disabled={removeBooking.isPending}
                    onClick={() => removeBooking.mutate(b.id)}
                    className="text-slate-400 hover:text-red-300 underline decoration-dotted">
                    {t('impl2.deleteBooking')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {mayWrite && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <input type="number" min={0} step="0.25" value={hours}
              data-testid={`impl-booking-hours-${id}`} aria-label={t('impl2.hours')}
              placeholder={t('impl2.hours')}
              onChange={(e) => setHours(e.target.value)}
              className={`w-24 ${fieldCls}`} />
            <input type="text" value={bookingNote}
              data-testid={`impl-booking-note-${id}`} aria-label={t('impl2.bookingNote')}
              placeholder={t('impl2.bookingNote')}
              onChange={(e) => setBookingNote(e.target.value)}
              className={`flex-1 min-w-[10rem] ${fieldCls}`} />
            <button type="button" data-testid={`impl-booking-add-${id}`}
              disabled={!hoursOk || addBooking.isPending}
              onClick={() => addBooking.mutate()}
              className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
              {t('impl2.addBooking')}
            </button>
          </div>
        )}
      </div>

      {/* Progress reports */}
      <div className="space-y-1 border-t border-slate-700 pt-2">
        <p className="text-xs font-medium text-slate-400">{t('impl2.reports')}</p>
        {reports.length === 0 ? (
          <p className="text-xs text-slate-500">{t('impl2.noReports')}</p>
        ) : (
          <ul className="space-y-1">
            {reports.map((r) => (
              <li key={r.id} data-testid={`impl-report-${r.id}`}
                className="rounded border border-slate-700 bg-slate-900/40 px-2 py-1 text-xs">
                <span className="flex items-start gap-2">
                  {r.at_risk && (
                    <span data-testid={`impl-report-risk-${r.id}`}
                      className="flex-shrink-0 rounded bg-red-900/80 text-red-100 px-1.5 py-0 text-[10px] leading-tight font-semibold">
                      {t('impl2.atRisk')}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block text-slate-200">{r.note}</span>
                    {r.at_risk && r.risk_note && (
                      <span data-testid={`impl-report-risknote-${r.id}`}
                        className="block text-red-200/90">{r.risk_note}</span>
                    )}
                    <span className="block text-slate-500">
                      {r.created_by_name ?? '—'}{r.created_at ? ` · ${onDay(r.created_at)}` : ''}
                    </span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {mayWrite && (
          <div className="space-y-1 pt-1">
            <textarea rows={2} value={reportNote}
              data-testid={`impl-report-note-${id}`} aria-label={t('impl2.reportNote')}
              placeholder={t('impl2.reportNote')}
              onChange={(e) => setReportNote(e.target.value)}
              className={`w-full ${fieldCls}`} />
            <label className="flex items-center gap-2 text-xs cursor-pointer">
              <input type="checkbox" data-testid={`impl-report-atrisk-${id}`}
                checked={atRisk} onChange={(e) => setAtRisk(e.target.checked)} />
              <span className="text-slate-300">{t('impl2.atRiskToggle')}</span>
            </label>
            {/* The flag opens the field that justifies it, and nothing sends
                until it is filled. */}
            {atRisk && (
              <div className="space-y-1">
                <textarea rows={2} value={riskNote}
                  data-testid={`impl-report-risknote-input-${id}`} aria-label={t('impl2.riskNote')}
                  placeholder={t('impl2.riskNote')}
                  onChange={(e) => setRiskNote(e.target.value)}
                  className={`w-full ${fieldCls}`} />
                {riskNote.trim() === '' && (
                  <p data-testid={`impl-report-riskrequired-${id}`} className="text-[11px] text-amber-300">
                    {t('impl2.riskNoteRequired')}
                  </p>
                )}
              </div>
            )}
            <button type="button" data-testid={`impl-report-add-${id}`}
              disabled={!reportOk || addReport.isPending}
              onClick={() => addReport.mutate()}
              className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
              {t('impl2.addReport')}
            </button>
          </div>
        )}
      </div>

      {/* Escalations — read by everyone who reads the block, written by Sales. */}
      <div className="space-y-1 border-t border-slate-700 pt-2">
        <p className="text-xs font-medium text-slate-400">{t('impl2.escalations')}</p>
        <EscalationList items={escalations} changeId={changeId}
          editable={editable} canEscalate={canEscalate}
          testPrefix={`impl-escalation-${id}`} />

        {/* A red flag that nobody has taken anywhere is the failure mode this
            whole stage exists to prevent — so it is said out loud, to Sales. */}
        {state.at_risk_open && !openEscalation && canEscalate && editable && (
          <p data-testid={`impl-escalation-hint-${id}`}
            className="rounded border border-amber-700/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-200">
            {t('impl2.escalationHint')}
          </p>
        )}

        {canEscalate && editable && (escalating ? (
          <div className="space-y-1 pt-1">
            <div className="flex items-center gap-2 flex-wrap">
              {DIRECTIONS.map((d) => (
                <label key={d} className="flex items-center gap-1 text-xs cursor-pointer">
                  <input type="radio" name={`impl-escalation-direction-pick-${id}`}
                    data-testid={`impl-escalation-direction-${d}-${id}`}
                    checked={direction === d} onChange={() => setDirection(d)} />
                  <span className="text-slate-300">{t(`impl2.direction.${d}`)}</span>
                </label>
              ))}
            </div>
            <textarea rows={2} value={escalationNote}
              data-testid={`impl-escalation-note-${id}`} aria-label={t('impl2.escalationNote')}
              placeholder={t('impl2.escalationNote')}
              onChange={(e) => setEscalationNote(e.target.value)}
              className={`w-full ${fieldCls}`} />
            <div className="flex items-center gap-2">
              <button type="button" data-testid={`impl-escalation-submit-${id}`}
                disabled={!escalationNote.trim() || addEscalation.isPending}
                onClick={() => addEscalation.mutate()}
                className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
                {t('impl2.addEscalation')}
              </button>
              <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
                onClick={() => { setEscalating(false); setEscalationNote('') }}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <button type="button" data-testid={`impl-escalation-open-${id}`}
            onClick={() => setEscalating(true)}
            className="text-xs text-sky-300 hover:text-sky-200">
            + {t('impl2.addEscalation')}
          </button>
        ))}
      </div>
    </section>
  )
}

export default function ImplementationTracking({
  changeId, status, departments, myDepartmentIds, canSeeAll, canEscalate = false,
}: {
  changeId: number
  status: string
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  /** PM, Sales, the change lead and admins see every department's block. */
  canSeeAll: boolean
  /** Sales, the change lead and admins raise and settle escalations. */
  canEscalate?: boolean
}) {
  // The backend only takes writes while the work is running; afterwards the
  // card is the record, for the implementing department too.
  const editable = status === 'in_implementation'

  const { data: state = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-state'],
    queryFn: () => changesApi.implementationState(changeId),
  })
  const { data: bookings = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-bookings'],
    queryFn: () => changesApi.listImplBookings(changeId),
  })
  const { data: reports = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-reports'],
    queryFn: () => changesApi.listImplReports(changeId),
  })
  const { data: escalations = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-escalations'],
    queryFn: () => changesApi.listImplEscalations(changeId),
  })
  // Shares the costing board's cache key, so the header line is free whenever
  // the commercial tab has already been opened.
  const { data: positions = [] } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  })

  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
  const leadTimes = vendorLeadTimeLine(positions)

  // Newest first everywhere: what happened last is what people came to read.
  const byNewest = <T extends { created_at?: string | null; id: number }>(rows: T[]) =>
    [...rows].sort((a, b) =>
      (b.created_at ?? '').localeCompare(a.created_at ?? '') || b.id - a.id)

  const visible = canSeeAll
    ? state
    : state.filter((s) => myDepartmentIds.includes(s.department_id))
  const others = state.length - visible.length

  // An escalation finds its block through the report it answers. One that
  // answers no report belongs to the change, not to a department, and is listed
  // once rather than repeated in every block.
  const reportDept = new Map(reports.map((r) => [r.id, r.department_id]))
  const escalationsOf = (deptId: number) => byNewest(escalations.filter(
    (e) => e.report_id != null && reportDept.get(e.report_id) === deptId))
  const looseEscalations = byNewest(escalations.filter(
    (e) => e.report_id == null || !reportDept.has(e.report_id)))

  return (
    <section data-testid="implementation-tracking" className="space-y-2">
      <div>
        <span className="font-medium text-slate-100">{t('impl2.title')}</span>
        <p className="text-xs text-slate-400 mt-0.5">{t('impl2.intro')}</p>
        {leadTimes && (
          <p data-testid="impl-vendor-leadtimes" className="text-xs text-slate-500 mt-0.5">
            {leadTimes}
          </p>
        )}
        {!editable && (
          <p data-testid="impl-tracking-readonly" className="text-xs text-slate-500 mt-0.5">
            {t('impl2.readOnly')}
          </p>
        )}
      </div>

      {state.length === 0 && (
        <p data-testid="impl-tracking-none" className="text-sm text-slate-400">
          {t('impl2.none')}
        </p>
      )}

      {visible.map((s) => (
        <DepartmentBlock key={s.department_id} changeId={changeId} state={s}
          name={deptName(s.department_id)}
          isMine={myDepartmentIds.includes(s.department_id)}
          editable={editable} canEscalate={canEscalate}
          bookings={byNewest(bookings.filter((b) => b.department_id === s.department_id))}
          reports={byNewest(reports.filter((r) => r.department_id === s.department_id))}
          escalations={escalationsOf(s.department_id)} />
      ))}

      {/* Everyone else, in one line: enough to know the change does not rest on
          this department alone, without showing work they may not read. */}
      {!canSeeAll && others > 0 && (
        <p data-testid="impl-tracking-others" className="text-xs text-slate-400 px-1 py-1">
          {t('impl2.others').replace('{n}', String(others))}
        </p>
      )}

      {looseEscalations.length > 0 && (
        <div data-testid="impl-escalations-change" className="space-y-1 pt-1">
          <p className="text-xs font-medium text-slate-400">{t('impl2.escalationsChange')}</p>
          <EscalationList items={looseEscalations} changeId={changeId}
            editable={editable} canEscalate={canEscalate} testPrefix="impl-escalation-change" />
        </div>
      )}
    </section>
  )
}

/**
 * The Offer tab: Sales' workspace from closed costing to the customer's
 * answer (spec 2026-09-25 sections 1 and 6). One page, five sections with a
 * sticky mini-nav, the server's offer sum always in view. Internal changes
 * get the Approval variant: the cost summary, the quote plan and PM's
 * internal cost approval.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changeOfferApi } from '../../../api/changeOffer'
import type { ChangeDetail } from '../../../types/change'
import type { OfferIssue, OfferOut } from '../../../types/changeOffer'
import NegotiationCard from '../NegotiationCard'
import CustomerDecision from './CustomerDecision'
import InternalApproval from './InternalApproval'
import OfferDocumentSection from './OfferDocumentSection'
import OfferPriceSection from './OfferPriceSection'
import OfferRisksSection from './OfferRisksSection'
import OfferSumCard from './OfferSumCard'
import OfferTimingSection from './OfferTimingSection'
import SendOfferDialog from './SendOfferDialog'
import {
  daysLeftTone, fmtDate, fmtMoney, fmtPct, fmtPiece, offerDaysLeft, quotePlanKey, resultTone, sectionLabel, validityText,
} from './offerFormat'
import { offersKey, useOfferDraft } from './useOfferDraft'
import { StepSection } from './ui'
import { planApi } from '../../../api/changePlan'

const useQuotePlan = (changeId: number) => useQuery({
  queryKey: quotePlanKey(changeId),
  queryFn: () => planApi.get(changeId, 'quote'),
})
const planHasTasks = (p?: { tasks?: unknown[] }) => (p?.tasks?.length ?? 0) > 0

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export interface OfferTabProps {
  change: ChangeDetail
  /** Sales, the change lead, admin: build, edit and send. */
  canWrite: boolean
  /** canWrite plus PM: read the prices. */
  canSeePrices: boolean
  canSignPm: boolean
  canSignQuality: boolean
  canApproveInternalCosts: boolean
  userId: number | null
  /** Internal changes: the cost summary (SummationView) the page renders. */
  costSummary?: ReactNode
}

type SectionId = 'offer-timing' | 'offer-price' | 'offer-risks' | 'offer-document' | 'offer-negotiation'

const SECTION_OF = (code: string): SectionId => {
  const c = code.toLowerCase()
  if (/timing|plan|week/.test(c)) return 'offer-timing'
  if (/risk/.test(c)) return 'offer-risks'
  if (/recipient|subject|term|document|rough|intro/.test(c)) return 'offer-document'
  if (/expir|valid|negotiat/.test(c)) return 'offer-negotiation'
  return 'offer-price'
}

const scrollTo = (id: string) => {
  const el = document.getElementById(id)
  if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** Opens the rendered PDF of a version in a new tab through a blob URL. */
function useOpenPdf(changeId: number, offerId: number) {
  const [busy, setBusy] = useState(false)
  const open = async () => {
    // Open the tab synchronously so the popup blocker lets it through.
    const win = window.open('', '_blank')
    setBusy(true)
    try {
      const blob = await changeOfferApi.pdf(changeId, offerId)
      const url = URL.createObjectURL(blob instanceof Blob ? blob : new Blob([blob], { type: 'application/pdf' }))
      if (win) win.location.href = url
      else window.open(url, '_blank')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      win?.close()
      toast.error(errDetail(e) ?? 'Could not render the PDF')
    } finally {
      setBusy(false)
    }
  }
  return { open, busy }
}

function PdfButton({ changeId, offerId, testId = 'offer-preview-pdf' }: {
  changeId: number; offerId: number; testId?: string
}) {
  const { open, busy } = useOpenPdf(changeId, offerId)
  return (
    <button type="button" data-testid={testId} disabled={busy} onClick={() => { void open() }}
      className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-50">
      {busy ? 'Rendering' : 'Preview PDF'}
    </button>
  )
}

function OfferHeader({
  change, offer, latestSent, canWrite, onSend, onNewVersion, creating, warnings, stale, sendBlocked, sending,
  onDiscard, discarding,
}: {
  change: ChangeDetail
  offer: OfferOut
  latestSent?: OfferOut
  canWrite: boolean
  onSend: () => void
  onNewVersion?: () => void
  creating?: boolean
  warnings: OfferIssue[]
  /** Local edits not saved yet: the totals are about to change. */
  stale?: boolean
  /** A save is pending or running: Send waits for it. */
  sendBlocked?: boolean
  sending?: boolean
  /** Throw the draft away (draft only). */
  onDiscard?: () => void
  discarding?: boolean
}) {
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const tot = offer.totals
  const cur = offer.currency || 'EUR'
  const statusLabel = offer.status === 'draft' ? 'Draft' : offer.status[0].toUpperCase() + offer.status.slice(1)
  const validRef = offer.status === 'draft' ? latestSent : offer
  return (
    <div data-testid="offer-header" className="rounded-xl border border-slate-700 bg-gradient-to-b from-slate-800 to-slate-800/60 p-4">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
        <div>
          <div className={sectionLabel}>Offer</div>
          <div className="mt-1 flex items-center gap-2">
            <span data-testid="offer-status"
              className={`rounded-full px-2.5 py-0.5 text-sm font-semibold ${offer.status === 'draft'
                ? 'bg-slate-700 text-slate-100' : offer.status === 'accepted' ? 'bg-emerald-800 text-emerald-100'
                : offer.status === 'declined' ? 'bg-rose-900 text-rose-100' : 'bg-sky-800 text-sky-100'}`}>
              {statusLabel} v{offer.version}
            </span>
            {validRef?.status === 'accepted' ? (
              // The accepted offer's own pill already says it; a newer draft names it.
              validRef.id !== offer.id && (
                <span data-testid="offer-valid-chip"
                  className="rounded-full border border-emerald-800 bg-emerald-950/60 px-2 py-0.5 text-[11px] text-emerald-200">
                  v{validRef.version} accepted
                </span>
              )
            ) : validRef?.valid_until && (
              <span data-testid="offer-valid-chip"
                className={`rounded-full border px-2 py-0.5 text-[11px] tabular-nums ${daysLeftTone(offerDaysLeft(validRef), validRef.expired)}`}>
                {validRef.status === offer.status ? '' : `v${validRef.version} `}
                valid until {fmtDate(validRef.valid_until)}
                {validityText(validRef) && <>{' · '}{validityText(validRef)}</>}
              </span>
            )}
          </div>
        </div>
        <div data-testid="offer-header-totals" data-stale={stale ? 'true' : undefined}
          title={stale ? 'Saving your changes, the totals update when the server answers' : undefined}
          className={`flex flex-wrap items-start gap-x-8 gap-y-3 transition-opacity ${stale ? 'opacity-50' : ''}`}>
        <div>
          <div className={sectionLabel}>Total one-time</div>
          <div data-testid="offer-total" className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-50">
            {fmtMoney(tot.total_one_time, cur)}
          </div>
        </div>
        <div>
          <div className={sectionLabel}>Piece price</div>
          <div data-testid="offer-piece" className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-100">
            {tot.piece_price_delta != null ? fmtPiece(tot.piece_price_delta, cur) : '-'}
          </div>
        </div>
        <div>
          <div className={sectionLabel}>Result vs internal cost</div>
          <div data-testid="offer-margin"
            className={`mt-0.5 text-lg font-semibold tabular-nums ${resultTone(tot.margin_abs)}`}>
            {fmtMoney(tot.margin_abs, cur)}
            {tot.margin_pct != null && <span className="ml-1 text-xs text-slate-500">{fmtPct(tot.margin_pct)}</span>}
          </div>
        </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 self-center">
          <PdfButton changeId={change.id} offerId={offer.id} />
          {canWrite && offer.status === 'draft' && (
            <button type="button" data-testid="offer-send" onClick={onSend}
              disabled={sendBlocked || sending}
              title={sendBlocked ? 'Saving your changes first' : undefined}
              className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50">
              {sending ? 'Saving' : 'Send offer'}
            </button>
          )}
          {onDiscard && offer.status === 'draft' && (confirmDiscard ? (
            <span data-testid="offer-discard-confirm" role="alertdialog" aria-label="Confirm discarding the draft"
              className="flex items-center gap-1.5 rounded-lg border border-rose-900/70 bg-rose-950/30 px-2 py-1 text-xs text-rose-200">
              Discard draft v{offer.version}? This cannot be undone.
              <button type="button" onClick={() => setConfirmDiscard(false)}
                className="rounded border border-slate-600 px-2 py-0.5 text-slate-300 hover:bg-slate-700">Keep</button>
              <button type="button" data-testid="offer-discard-yes" disabled={discarding}
                onClick={onDiscard}
                className="rounded bg-rose-700 px-2 py-0.5 font-medium text-white hover:bg-rose-600 disabled:opacity-50">
                Discard
              </button>
            </span>
          ) : (
            <button type="button" data-testid="offer-discard" onClick={() => setConfirmDiscard(true)}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:border-rose-700 hover:text-rose-200">
              Discard draft
            </button>
          ))}
          {onNewVersion && (
            <button type="button" data-testid="offer-new-version" disabled={creating} onClick={onNewVersion}
              className="rounded-lg border border-sky-700 px-3 py-1.5 text-sm text-sky-200 hover:bg-sky-900/40 disabled:opacity-50">
              New version
            </button>
          )}
        </div>
      </div>
      {warnings.length > 0 && (
        <ul data-testid="offer-warnings" className="mt-3 flex flex-wrap gap-1.5">
          {warnings.map((w, i) => (
            <li key={`${w.code}-${i}`}>
              <button type="button" onClick={() => scrollTo(SECTION_OF(w.code))}
                className="rounded-md border border-amber-800/70 bg-amber-950/30 px-2 py-0.5 text-[11px] text-amber-200 hover:bg-amber-900/40">
                ⚠ {w.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const NAV: { id: SectionId; label: string }[] = [
  { id: 'offer-timing', label: 'Timing' },
  { id: 'offer-price', label: 'Price' },
  { id: 'offer-risks', label: 'Risks' },
  { id: 'offer-document', label: 'Document' },
  { id: 'offer-negotiation', label: 'Negotiation' },
]

function OfferWorkspace({ props, offers, offer }: {
  props: OfferTabProps
  offers: OfferOut[]
  offer: OfferOut
}) {
  const { change, canWrite } = props
  const qc = useQueryClient()
  const [sendOpen, setSendOpen] = useState(false)
  const [preparingSend, setPreparingSend] = useState(false)
  const editable = canWrite && offer.status === 'draft' && ['quoting', 'quoted'].includes(change.status)
  const { data, update, saveState, flush, dirty } = useOfferDraft(change.id, offer)
  // Send only what the server has: wait for the save, then open the dialog,
  // which reads the saved offer (fresh totals) from the cache.
  const openSend = async () => {
    setPreparingSend(true)
    try {
      if (await flush()) setSendOpen(true)
    } finally {
      setPreparingSend(false)
    }
  }
  const latestSent = offers.find((o) => o.status === 'sent' || o.status === 'accepted')
  const hasDraft = offers.some((o) => o.status === 'draft')
  const { data: plan } = useQuotePlan(change.id)
  const pdf = useOpenPdf(change.id, offer.id)
  const cur = offer.currency || 'EUR'
  const showNegotiation = ['quoted', 'approved', 'in_implementation', 'in_validation', 'released', 'closed']
    .includes(change.status) || !!latestSent

  const refresh = useMutation({
    // Save what was typed first; if that save failed (already reported), do
    // not refresh over the unsaved edits.
    mutationFn: async () => ((await flush()) ? changeOfferApi.refresh(change.id, offer.id) : null),
    onSuccess: (o) => {
      if (!o) return
      qc.setQueryData<OfferOut[]>(offersKey(change.id), (old) => (old ?? []).map((x) => (x.id === o.id ? o : x)))
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not refresh from costing'),
  })
  const newVersion = useMutation({
    mutationFn: () => changeOfferApi.create(change.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: offersKey(change.id) }),
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not create a new version'),
  })
  const discard = useMutation({
    mutationFn: () => changeOfferApi.discard(change.id, offer.id),
    onSuccess: () => {
      toast.success(`Draft v${offer.version} discarded`)
      qc.invalidateQueries({ queryKey: offersKey(change.id) })
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', change.id] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not discard the draft'),
  })

  const done: Record<SectionId, boolean> = {
    'offer-timing': data.timing?.include === false
      || (planHasTasks(plan) && (data.timing?.weeks_from_order ?? 0) > 0),
    'offer-price': (offer.totals.total_one_time ?? 0) > 0,
    'offer-risks': !(data.risks ?? []).some((r) => r.severity === 3 && !r.show),
    'offer-document': !!data.recipient?.company && !!data.subject
      && (data.cbd_mode !== 'rough' || !!data.rough_description),
    'offer-negotiation': change.customer_response === 'accepted',
  }
  const nav = NAV.filter((n) => n.id !== 'offer-negotiation' || showNegotiation)

  return (
    <div className="space-y-4">
      <OfferHeader change={change} offer={offer} latestSent={latestSent} canWrite={canWrite}
        warnings={offer.warnings ?? []}
        stale={dirty}
        sendBlocked={saveState === 'pending' || saveState === 'saving'}
        sending={preparingSend}
        onSend={() => { void openSend() }}
        onNewVersion={canWrite && !hasDraft && change.status === 'quoted' ? () => newVersion.mutate() : undefined}
        creating={newVersion.isPending}
        onDiscard={editable ? () => discard.mutate() : undefined}
        discarding={discard.isPending} />

      <nav data-testid="offer-nav"
        className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-1 rounded-lg border border-slate-700/80 bg-slate-900/90 px-2 py-1.5 backdrop-blur">
        {nav.map((n, i) => (
          <a key={n.id} href={`#${n.id}`} data-testid={`nav-${n.id}`}
            onClick={(e) => { e.preventDefault(); scrollTo(n.id) }}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 hover:text-slate-100">
            <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${done[n.id]
              ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
              {done[n.id] ? '✓' : i + 1}
            </span>
            {n.label}
          </a>
        ))}
        {!editable && (
          <span className="ml-auto text-[11px] text-slate-500">
            {offer.status === 'draft' ? 'Read only: Sales, the change lead and admins edit the offer.' : `v${offer.version} is ${offer.status}, read only.`}
          </span>
        )}
      </nav>

      {/* The Gantt planner is its own tool and stays interactive while a
          refresh runs; only the offer's own timing fields (and the other
          sections below) wait for the refreshed draft. The timing gets the
          full page width: a Gantt needs it more than the sum card beside it. */}
      <StepSection id="offer-timing" n={1} title="Timing" done={done['offer-timing']}>
        <OfferTimingSection changeId={change.id} changeNumber={change.change_number} data={data} update={update} editable={editable}
          fieldsDisabled={refresh.isPending} />
      </StepSection>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0 space-y-4">
          {/* While a refresh runs the server rewrites the draft: no typing into it meanwhile. */}
          <fieldset disabled={refresh.isPending} aria-busy={refresh.isPending} data-testid="offer-edit-fieldset"
            className="m-0 min-w-0 space-y-4 border-0 p-0">
          <StepSection id="offer-price" n={2} title="Price" done={done['offer-price']}>
            <OfferPriceSection data={data} update={update} editable={editable} currency={cur}
              annualEffect={offer.totals.annual_effect}
              onRefresh={() => refresh.mutate()} refreshing={refresh.isPending}
              warnings={offer.warnings ?? []} />
          </StepSection>
          <StepSection id="offer-risks" n={3} title="Risks" done={done['offer-risks']}
            hint="Choose which risks the customer reads and price a surcharge where a risk is real money.">
            <OfferRisksSection data={data} update={update} editable={editable} currency={cur}
              risksTotal={offer.totals.risks_total ?? 0} />
          </StepSection>
          <StepSection id="offer-document" n={4} title="Document" done={done['offer-document']}>
            <OfferDocumentSection offer={offer} data={data} update={update} editable={editable}
              changeNumber={change.change_number}
              onPreview={() => { void pdf.open() }} previewing={pdf.busy} />
          </StepSection>
          </fieldset>
          {showNegotiation && (
            <StepSection id="offer-negotiation" n={5} title="Negotiation" done={done['offer-negotiation']}
              hint="Every version sent and every round with the customer, in order. A new version needs a note on what changed.">
              <NegotiationCard changeId={change.id} status={change.status} canWrite={canWrite}
                offerId={latestSent?.id ?? null} offers={offers} />
              <CustomerDecision change={change} latestSent={latestSent}
                canRespond={canWrite} canSignPm={props.canSignPm}
                canSignQuality={props.canSignQuality} userId={props.userId} />
            </StepSection>
          )}
        </div>
        <div className="xl:sticky xl:top-14 xl:self-start">
          <OfferSumCard offer={offer} saveState={saveState} stale={dirty} />
        </div>
      </div>

      {sendOpen && <SendOfferDialog changeId={change.id} offerId={offer.id} fallback={offer}
        onClose={() => setSendOpen(false)} />}
    </div>
  )
}

function StageHeader({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3">
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      <p className="mt-0.5 text-xs text-slate-400">{body}</p>
    </div>
  )
}

export default function OfferTab(props: OfferTabProps) {
  const { change, canWrite, canSeePrices } = props
  const qc = useQueryClient()
  const { data: plan } = useQuotePlan(change.id)
  const timingDone = planHasTasks(plan)
  const customer = !!change.customer_relevant
  const offerStage = ['quoting', 'quoted', 'approved', 'in_implementation', 'in_validation', 'released', 'closed',
    'rejected', 'on_hold', 'cancelled'].includes(change.status)

  const { data: offers = [], isLoading } = useQuery({
    queryKey: offersKey(change.id),
    queryFn: () => changeOfferApi.list(change.id),
    enabled: customer && canSeePrices && offerStage,
  })
  const current = useMemo(
    () => offers.find((o) => o.status === 'draft') ?? offers[0],
    [offers])

  const start = useMutation({
    mutationFn: () => changeOfferApi.create(change.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: offersKey(change.id) }),
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not start the offer'),
  })

  // Internal changes: approval, not an offer.
  if (!customer) {
    return (
      <div className="space-y-4">
        <StageHeader title="Internal approval"
          body="Internal changes are not offered. PM approves the costs; the quote plan gives the change its timing before approval." />
        {canSeePrices && props.costSummary}
        <StepSection id="offer-timing" n={1} title="Timing" done={timingDone}>
          <OfferTimingSection changeId={change.id} changeNumber={change.change_number} editable={false} />
        </StepSection>
        <StepSection id="offer-approval" n={2} title="Approval" done={!!change.internal_approved_at}>
          <InternalApproval change={change} canApprove={props.canApproveInternalCosts} />
        </StepSection>
      </div>
    )
  }

  if (!canSeePrices) {
    return (
      <div className="space-y-4">
        <p data-testid="offer-no-access"
          className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3 text-sm text-slate-400">
          Offer prices are visible to Sales, the Project Manager, the change lead and admins.
        </p>
        {change.status === 'quoted' && (props.canSignQuality || props.canSignPm) && (
          <CustomerDecision change={change} canRespond={false} canSignPm={props.canSignPm}
            canSignQuality={props.canSignQuality} userId={props.userId} />
        )}
      </div>
    )
  }

  const header = (
    <StageHeader title="Offer"
      body="Sales builds the offer from closed costing: rough timing, price, risks and the document. Sending v1 moves the change to Quoted; each sent version is valid 30 days from receipt." />
  )

  if (change.status === 'costing') {
    return (
      <div className="space-y-4">
        {header}
        <p data-testid="offer-waits-costing"
          className="rounded-lg border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-slate-400">
          The offer opens when costing is closed. The rough timing can be prepared already.
        </p>
        <StepSection id="offer-timing" n={1} title="Timing" done={timingDone}>
          <OfferTimingSection changeId={change.id} changeNumber={change.change_number} editable={false} />
        </StepSection>
      </div>
    )
  }

  if (isLoading) return <p className="text-sm text-slate-500">Loading offer</p>

  if (!current) {
    const canStart = canWrite && ['quoting', 'quoted'].includes(change.status)
    return (
      <div className="space-y-4">
        {header}
        <div data-testid="offer-empty"
          className="flex flex-col items-center rounded-xl border border-dashed border-slate-600 bg-slate-800/40 px-6 py-10 text-center">
          <h3 className="text-base font-semibold text-slate-100">No offer yet</h3>
          <p className="mt-1 max-w-md text-sm text-slate-400">
            Starting the offer pre-fills it from costing: one cost line per department and external position,
            the standard factors (off), the open risks, the changeover mode and the rough timing from the quote plan.
          </p>
          {canStart ? (
            <button type="button" data-testid="offer-start" disabled={start.isPending}
              onClick={() => start.mutate()}
              className="mt-4 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
              Start the offer
            </button>
          ) : (
            <p className="mt-3 text-xs text-slate-500">
              {canWrite ? 'Offers are created while the change is in quote creation or quoted.' : 'Sales starts the offer.'}
            </p>
          )}
        </div>
        <StepSection id="offer-timing" n={1} title="Timing" done={timingDone}>
          <OfferTimingSection changeId={change.id} changeNumber={change.change_number} editable={false} />
        </StepSection>
        {change.status === 'quoted' && (
          <CustomerDecision change={change} canRespond={canWrite} canSignPm={props.canSignPm}
            canSignQuality={props.canSignQuality} userId={props.userId} />
        )}
      </div>
    )
  }

  // Keyed by id: a new version starts with fresh local draft state.
  return <OfferWorkspace key={current.id} props={props} offers={offers} offer={current} />
}

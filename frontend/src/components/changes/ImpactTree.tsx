import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check } from 'lucide-react'
import { changesApi } from '../../api/changes'
import Button from '../common/Button'
import ConfirmDialog from '../common/ConfirmDialog'
import EmptyState from '../common/EmptyState'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import type { AssessmentObject, ChangeStatus, ImpactTreeNode } from '../../types/change'
import { t } from '../../i18n/cmLabels'
import { formatDateTime } from '../../lib/format'
import { groupItems } from '../../lib/itemCategory'
import ReasonDialog from './ReasonDialog'
import TransitionConfirmDialog from './TransitionConfirmDialog'

const LOCKED: ChangeStatus[] = [
  'in_implementation', 'in_validation', 'released', 'closed', 'rejected', 'cancelled',
]

// The lead names the change, so it is pinned from assessment on: by then
// departments have been routed against it. While the change is still being
// captured or scoped, picking the wrong lead is an ordinary mistake and stays
// correctable. Mirrors the lead_editable check in ChangeService.apply_impact_selection.
const LEAD_EDITABLE: ChangeStatus[] = ['captured', 'scoping']

/** Tools, gauges and equipment serve parts; documents and parts do not. */
const SERVING_TYPES = new Set(['tool', 'gauge', 'equipment'])

interface Props {
  changeId: number
  status: ChangeStatus
  impactConfirmedByName?: string | null
  impactConfirmedAt?: string | null
  /** Whether the current user may confirm impact (Development member).
      Defaults to true so existing callers keep prior behaviour. */
  canConfirm?: boolean
  /** Impact set edits are the change lead's, PM's and admin's (spec §16 P1 5).
      false renders the tree read only: no selection, no Apply. */
  canEdit?: boolean
  /** The title is composed from the lead item and follows it. */
  titleAuto?: boolean
  /** The impact moved after the offer went out: the offer no longer covers it. */
  scopeChangedAfterQuote?: boolean
  /** The offer has gone out: a changed set needs a reason on the record. */
  quoted?: boolean
  /** Called after the set (or the lead) changed on the server. */
  onChanged?: () => void
  /** 'engineering_review': the lock opens the review, no assessment is routed. */
  origin?: string | null
}

const sortedKey = (ids: Iterable<number>) => [...ids].sort((a, b) => a - b).join(',')

export default function ImpactTree({
  changeId, status, impactConfirmedByName, impactConfirmedAt, canConfirm = true,
  canEdit = true, titleAuto = false, scopeChangedAfterQuote = false, quoted = false, onChanged,
  origin = null,
}: Props) {
  const qc = useQueryClient()
  const phaseOpen = !LOCKED.includes(status)
  const editable = phaseOpen && canEdit
  const leadPinned = !LEAD_EDITABLE.includes(status)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Which gate the Apply click is waiting behind: the post-quote reason, or
  // the warning that Development's confirmation will be cleared.
  const [asking, setAsking] = useState<'reason' | 'lock' | null>(null)
  // Confirming locks the set the assessment is routed on: asked once more.
  const [confirmingImpact, setConfirmingImpact] = useState(false)

  const confirmImpact = useMutation({
    mutationFn: () => changesApi.confirmImpact(changeId),
    onSuccess: () => {
      toast.success('Impact confirmed')
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      // The cockpit's "Your actions" reads its own query: without this the
      // "Confirm impacted items" line stays until a reload.
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    },
    onError: (e: unknown) => { toastError(e, 'Could not confirm the impact') },
  })

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'impact-tree'],
    queryFn: () => changesApi.getImpactTree(changeId),
  })
  // Same cache entry as the detail page: the impacted items carry the ids
  // "Make lead" acts on.
  const { data: change } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
    enabled: editable && !leadPinned,
  })
  // What each department assesses, per the impacted set: the tools, gauges and
  // equipment that serve a part (via_part_id). Shared with the assessment tab.
  const { data: objectData } = useQuery({
    queryKey: ['change-assessment-objects', changeId],
    queryFn: () => changesApi.assessmentObjects(changeId),
    retry: false,
  })

  const lastSyncedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!data) return
    const serverKey = sortedKey(data.impacted_part_ids)
    const selectedNow = sortedKey(selected)
    // Only overwrite the user's in-progress selection if it hasn't diverged
    // from what we last synced from the server (i.e. no unsaved edits), or
    // this is the initial load. A background refetch (e.g. window focus)
    // that lands mid-edit must not clobber the user's checkbox changes.
    if (selectedNow === lastSyncedRef.current || lastSyncedRef.current === null) {
      setSelected(new Set(data.impacted_part_ids))
      lastSyncedRef.current = serverKey
    } else if (serverKey === selectedNow) {
      lastSyncedRef.current = serverKey
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const selectedKey = useMemo(() => [...selected].sort((a, b) => a - b), [selected])

  const { data: suggestion } = useQuery({
    queryKey: ['change', changeId, 'impact-suggest', selectedKey.join(',')],
    queryFn: () => changesApi.suggestImpact(changeId, selectedKey),
    enabled: editable && selectedKey.length > 0,
  })
  const suggested = useMemo(
    () => new Set(suggestion?.suggested_part_ids ?? []), [suggestion])

  // Before routing (capture, scoping) there are no assessment objects yet:
  // the served-by walk is asked for the parts as selected right now. An
  // older backend without the endpoint falls back to the assessment objects.
  const beforeRouting = status === 'captured' || status === 'scoping'
  const { data: impactObjects } = useQuery({
    queryKey: ['change', changeId, 'impact-objects', selectedKey.join(',')],
    queryFn: () => changesApi.impactObjects(changeId, selectedKey),
    enabled: beforeRouting && selectedKey.length > 0,
    retry: false,
    placeholderData: (prev) => prev,
  })

  // part id -> the tools/gauges/equipment serving it, once per object.
  const servedBy = useMemo(() => {
    const m = new Map<number, AssessmentObject[]>()
    if (beforeRouting && impactObjects?.parts) {
      for (const p of impactObjects.parts) {
        const list = (p.served_by ?? []).filter((o) => SERVING_TYPES.has(o.type))
        if (list.length > 0) m.set(p.part_id, list)
      }
      return m
    }
    for (const d of objectData?.departments ?? []) {
      for (const o of d.objects ?? []) {
        if (o.via_part_id == null || !SERVING_TYPES.has(o.type)) continue
        const list = m.get(o.via_part_id) ?? []
        if (!list.some((x) => x.type === o.type && x.id === o.id)) list.push(o)
        m.set(o.via_part_id, list)
      }
    }
    return m
  }, [objectData, impactObjects, beforeRouting])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impact-tree'] })
    qc.invalidateQueries({ queryKey: ['change-assessment-objects', changeId] })
    // Applying clears Development's confirmation: their action comes back.
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    onChanged?.()
  }

  const apply = useMutation({
    mutationFn: (reason?: string) => (reason
      ? changesApi.applyImpactSelection(changeId, selectedKey, reason)
      : changesApi.applyImpactSelection(changeId, selectedKey)),
    onSuccess: invalidate,
  })
  // A failure toasts only where nothing else shows it: the "apply anyway"
  // ConfirmDialog prints its own inline error, so it applies without this.
  const applyWithToast = (reason?: string) => apply.mutate(reason, {
    onError: (e: unknown) => { toastError(e, 'Could not apply the selection') },
  })

  const makeLead = useMutation({
    mutationFn: (itemId: number) => changesApi.makeLead(changeId, itemId),
    onSuccess: () => {
      toast.success(t('impact.leadChanged'))
      invalidate()
    },
    onError: (e: unknown) => { toastError(e, t('impact.makeLeadFailed')) },
  })

  const toggle = (partId: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(partId)) next.delete(partId)
      else next.add(partId)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4" aria-busy="true">
        <p className="sr-only">Loading the impacted items…</p>
        <div className="space-y-2" aria-hidden="true">
          {[0, 1, 2].map((i) => <div key={i} className="h-5 rounded bg-slate-700/70 motion-safe:animate-pulse" />)}
        </div>
      </div>
    )
  }
  if (!data || data.tree.length === 0) {
    return <EmptyState size="sm" title="No parts to pick from" hint={t('impact.empty')} />
  }

  const server = new Set(data.impacted_part_ids)
  const added = selectedKey.filter((id) => !server.has(id))
  const removed = data.impacted_part_ids.filter((id) => !selected.has(id))
  const dirty = added.length + removed.length > 0

  // Names, not ids, wherever a part is mentioned.
  // The impacted items carry their part number (backend fills it), so a
  // part no longer in the tree still reads by name; the tree fills the rest.
  const nameOf = new Map<number, string>()
  change?.impacted_items?.forEach((i) => { if (i.part_number) nameOf.set(i.part_id, i.part_number) })
  const walk = (n: ImpactTreeNode) => { nameOf.set(n.part_id, n.part_number); n.children.forEach(walk) }
  data.tree.forEach(walk)

  const startApply = () => {
    if (quoted) setAsking('reason')
    else if (impactConfirmedAt) setAsking('lock')
    else applyWithToast(undefined)
  }
  const discard = () => setSelected(new Set(data.impacted_part_ids))

  const itemIdOf = (partId: number) =>
    change?.impacted_items?.find((i) => i.part_id === partId)?.id

  const renderNode = (node: ImpactTreeNode, depth: number) => {
    const isSel = selected.has(node.part_id)
    const pendingAdd = isSel && !server.has(node.part_id)
    const pendingRemove = !isSel && server.has(node.part_id)
    const isSuggested = !isSel && suggested.has(node.part_id)
    const serving = servedBy.get(node.part_id) ?? []
    const locked = !editable || (node.is_lead && leadPinned) || node.resulting_revision_id !== null
    const leadItemId = !node.is_lead && server.has(node.part_id) && !pendingRemove
      ? itemIdOf(node.part_id) : undefined
    return (
      <div key={node.part_id}>
        <div
          data-testid={`impact-row-${node.part_id}`}
          data-pending={pendingAdd ? 'add' : pendingRemove ? 'remove' : undefined}
          className={`flex items-center gap-2 py-1 rounded hover:bg-slate-700/40 ${
            pendingAdd ? 'bg-sky-950/40' : pendingRemove ? 'bg-red-950/30'
            : isSuggested ? 'bg-amber-950/30' : ''}`}
          style={{ paddingLeft: `${depth * 20}px` }}
        >
          <input
            type="checkbox"
            className="accent-sky-500"
            aria-label={`${node.name} (${node.part_number})`}
            checked={isSel}
            disabled={locked}
            onChange={() => toggle(node.part_id)}
          />
          {/* Our number leads, the customer's follows, the name last: the same
              reading order as the change title and the start dialog. */}
          <span className="font-mono text-slate-100 text-sm flex-shrink-0">{node.part_number}</span>
          <span className="font-mono text-sky-300/80 text-xs flex-shrink-0 w-32">
            {node.customer_part_number ?? <span className="text-slate-600">-</span>}
          </span>
          <span className="text-slate-400 text-sm truncate min-w-0">{node.name}</span>
          {node.is_lead && (
            <span
              className={`px-2 py-0.5 rounded-full text-xs ${
                leadPinned ? 'bg-slate-700 text-slate-400' : 'bg-sky-900 text-sky-100'}`}
              title={leadPinned ? t('impact.leadPinned') : undefined}
            >
              {t('impact.lead')}
            </span>
          )}
          {pendingAdd && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-sky-900/70 text-sky-200"
              data-testid={`impact-pending-${node.part_id}`}>{t('impact.pendingAdd')}</span>
          )}
          {pendingRemove && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-red-900/70 text-red-200"
              data-testid={`impact-pending-${node.part_id}`}>{t('impact.pendingRemove')}</span>
          )}
          {node.resulting_revision_id !== null && (
            node.resulting_revision_pending ? (
              <span data-testid={`impact-resulting-${node.part_id}`}
                title="New customer index, pending: this change activates it at release"
                className="px-2 py-0.5 rounded-full text-xs bg-amber-900/70 text-amber-100">
                {node.resulting_revision_label ?? `#${node.resulting_revision_id}`} pending
              </span>
            ) : (
              <span data-testid={`impact-resulting-${node.part_id}`} title="Resulting revision"
                className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
                {node.resulting_revision_label ?? `ECN #${node.resulting_revision_id}`}
              </span>
            )
          )}
          {isSuggested && (
            <button
              type="button"
              data-testid={`impact-suggested-${node.part_id}`}
              onClick={() => !locked && toggle(node.part_id)}
              disabled={locked}
              className="px-2 py-0.5 rounded-full text-xs bg-amber-900 text-amber-100 hover:bg-amber-800 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-amber-900"
              title={t('impact.suggestedHint')}
            >
              {t('impact.suggested')}{locked ? '' : ' +'}
            </button>
          )}
          {editable && !leadPinned && leadItemId != null && (
            <button type="button" data-testid={`impact-make-lead-${node.part_id}`}
              disabled={makeLead.isPending}
              onClick={() => makeLead.mutate(leadItemId)}
              title={titleAuto ? t('impact.titleFollowsLead') : undefined}
              className="ml-auto flex-shrink-0 text-xs text-slate-400 hover:text-sky-300 disabled:opacity-50">
              {t('start.makeLead')}
            </button>
          )}
        </div>
        {serving.length > 0 && (
          <p data-testid={`impact-served-${node.part_id}`}
            className="text-[11px] text-slate-500 py-0.5"
            style={{ paddingLeft: `${depth * 20 + 24}px` }}>
            {t('impact.servedBy')}{' '}
            {serving.map((o, i) => (
              <span key={`${o.type}-${o.id}`}>
                {i > 0 && ', '}
                <span className="font-mono text-slate-300">{o.number}</span>{' '}
                <span>{t(`objtype.${o.type}`) === `objtype.${o.type}` ? o.type : t(`objtype.${o.type}`)}</span>
              </span>
            ))}
          </p>
        )}
        {node.children.map(c => renderNode(c, depth + 1))}
      </div>
    )
  }

  const pendingSummary = [
    added.length > 0 ? `+${added.map((id) => nameOf.get(id) ?? '?').join(', +')}` : '',
    removed.length > 0 ? `-${removed.map((id) => nameOf.get(id) ?? '?').join(', -')}` : '',
  ].filter(Boolean).join('  ')

  const lockWarning = impactConfirmedAt
    ? t('impact.lockWarning')
      .replace('{who}', impactConfirmedByName ?? 'Development')
      .replace('{when}', formatDateTime(impactConfirmedAt))
    : ''

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <TransitionConfirmDialog busy={confirmImpact.isPending}
        confirm={confirmingImpact ? {
          to: 'impact-confirm', title: t('impact.confirmTitle'),
          consequence: t(origin === 'engineering_review' ? 'impact.confirmBodyReview' : 'impact.confirmBody'),
          open: [],
          info: [t('impact.confirmCount').replace('{n}', String(data?.impacted_part_ids?.length ?? 0))],
          confirmLabel: t('impact.confirm'),
        } : null}
        onClose={() => setConfirmingImpact(false)}
        onConfirm={() => { setConfirmingImpact(false); confirmImpact.mutate() }} />
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div>
          <h3 className="text-slate-100 font-semibold">{t('impact.title')}</h3>
          <p className="text-slate-400 text-xs">{t('impact.hint')}</p>
          {titleAuto && !leadPinned && editable && (
            <p className="text-slate-500 text-xs" data-testid="impact-title-auto">
              {t('impact.titleFollowsLead')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {impactConfirmedAt ? (
            <span data-testid="impact-confirmed"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-950/60 text-emerald-200 ring-1 ring-inset ring-emerald-800/70">
              <Check aria-hidden="true" size={14} />
              {t('impact.confirmed')} {impactConfirmedByName ?? '-'} · {formatDateTime(impactConfirmedAt)}
            </span>
          ) : (
            // Shown to everyone, actionable only by Development: a greyed button
            // that names the rule beats a control that vanishes or 403s.
            <Button variant="primary"
              data-testid="impact-confirm"
              onClick={() => setConfirmingImpact(true)}
              disabled={!canConfirm || dirty}
              loading={confirmImpact.isPending}
              title={!canConfirm ? t('impact.developmentOnly') : dirty ? t('impact.applyFirst') : undefined}
            >
              {t('impact.confirm')}
            </Button>
          )}
          {editable ? (
            <Button onClick={startApply} disabled={!dirty} loading={apply.isPending}>
              {t('impact.apply')}
            </Button>
          ) : !phaseOpen ? (
            <span className="text-amber-300 text-xs">{t('impact.locked')}</span>
          ) : (
            <span className="text-slate-400 text-xs" data-testid="impact-readonly">{t('impact.editRights')}</span>
          )}
        </div>
      </div>

      {scopeChangedAfterQuote && (
        <p role="alert" data-testid="impact-scope-changed"
          className="mb-3 rounded-lg border border-amber-700/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
          {t('impact.scopeChangedAfterQuote')}
        </p>
      )}

      {dirty && editable && (
        <div data-testid="impact-pending-bar"
          className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-sky-800/60 bg-sky-950/40 px-3 py-2 text-xs text-sky-100">
          <span className="font-medium">
            {t('impact.notApplied').replace('{n}', String(added.length + removed.length))}
          </span>
          <span className="font-mono text-sky-200/80 truncate min-w-0">{pendingSummary}</span>
          <span className="ml-auto flex gap-2">
            <button type="button" onClick={discard} data-testid="impact-discard"
              className={btnSm.ghost}>
              {t('impact.discard')}
            </button>
            <button type="button" onClick={startApply} disabled={apply.isPending}
              data-testid="impact-apply-bar" className={btnSm.primary}>
              {t('impact.apply')}
            </button>
          </span>
        </div>
      )}

      {/* Roots grouped by controlled-item class, each behind a rule: Articles,
          Dunnage, Material, Tools, EOAT, … The BOM nesting under each root is
          untouched; grouping only orders the top level. */}
      {groupItems(data.tree).map(group => (
        <div key={group.key} className="border-t border-slate-700 first:border-t-0 first:pt-0 pt-2 mt-2">
          <div className="flex items-center gap-2 px-1 py-1 text-xs uppercase tracking-wide text-slate-500">
            <span>{group.label}</span>
            <span className="ml-auto normal-case">{group.items.length}</span>
          </div>
          {group.items.map(n => renderNode(n, 0))}
        </div>
      ))}

      <ReasonDialog
        open={asking === 'reason'}
        title={t('impact.afterQuoteTitle')}
        warning={[t('impact.afterQuoteWarning'), lockWarning].filter(Boolean).join(' ')}
        label={t('impact.afterQuoteLabel')}
        submitLabel={t('impact.apply')}
        onSubmit={(reason) => { setAsking(null); applyWithToast(reason) }}
        onClose={() => setAsking(null)}
      />
      <ConfirmDialog open={asking === 'lock'} data-testid="impact-lock-confirm"
        title={t('impact.lockTitle')} body={lockWarning}
        cancelLabel={t('impact.keepSet')} confirmLabel={t('impact.applyAnyway')}
        errorFallback="Could not apply the selection"
        onClose={() => setAsking(null)}
        onConfirm={() => apply.mutateAsync(undefined)} />
    </div>
  )
}

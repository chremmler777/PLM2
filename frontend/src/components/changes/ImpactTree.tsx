import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import type { ChangeStatus, ImpactTreeNode } from '../../types/change'
import { t } from '../../i18n/cmLabels'
import { groupItems } from '../../lib/itemCategory'

const LOCKED: ChangeStatus[] = [
  'in_implementation', 'in_validation', 'released', 'closed', 'rejected', 'cancelled',
]

// The lead names the change, so it is pinned from assessment on — by then
// departments have been routed against it. While the change is still being
// captured or scoped, picking the wrong lead is an ordinary mistake and stays
// correctable. Mirrors the lead_editable check in ChangeService.apply_impact_selection.
const LEAD_EDITABLE: ChangeStatus[] = ['captured', 'scoping']

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

interface Props {
  changeId: number
  status: ChangeStatus
  impactConfirmedByName?: string | null
  impactConfirmedAt?: string | null
  /** Task 19: whether the current user may confirm impact (Development member or
      admin — server-mirrored via GET /my-actions). Defaults to true so
      existing callers that don't pass it keep prior behaviour. */
  canConfirm?: boolean
}

export default function ImpactTree({ changeId, status, impactConfirmedByName, impactConfirmedAt, canConfirm = true }: Props) {
  const qc = useQueryClient()
  const editable = !LOCKED.includes(status)
  const leadPinned = !LEAD_EDITABLE.includes(status)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const confirmImpact = useMutation({
    mutationFn: () => changesApi.confirmImpact(changeId),
    onSuccess: () => {
      toast.success(t('impact.confirm'))
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Confirm failed'),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'impact-tree'],
    queryFn: () => changesApi.getImpactTree(changeId),
  })

  const lastSyncedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!data) return
    const serverKey = [...data.impacted_part_ids].sort((a, b) => a - b).join(',')
    const selectedNow = [...selected].sort((a, b) => a - b).join(',')
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

  const apply = useMutation({
    mutationFn: () => changesApi.applyImpactSelection(changeId, selectedKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impact-tree'] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Apply failed'),
  })

  const toggle = (partId: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(partId)) next.delete(partId)
      else next.add(partId)
      return next
    })
  }

  if (isLoading) return <div className="text-slate-400 text-sm">…</div>
  if (!data || data.tree.length === 0)
    return <div className="text-slate-400 text-sm">{t('impact.empty')}</div>

  const dirty =
    selectedKey.join(',') !== [...data.impacted_part_ids].sort((a, b) => a - b).join(',')

  const renderNode = (node: ImpactTreeNode, depth: number) => (
    <div key={node.part_id}>
      <div
        className="flex items-center gap-2 py-1 rounded hover:bg-slate-700/40"
        style={{ paddingLeft: `${depth * 20}px` }}
      >
        <input
          type="checkbox"
          className="accent-sky-500"
          aria-label={`${node.name} (${node.part_number})`}
          checked={selected.has(node.part_id)}
          disabled={!editable || (node.is_lead && leadPinned)
                    || node.resulting_revision_id !== null}
          onChange={() => toggle(node.part_id)}
        />
        {/* Our number leads, the customer's follows, the name last — the same
            reading order as the change title and the start dialog. */}
        <span className="font-mono text-slate-100 text-sm flex-shrink-0">{node.part_number}</span>
        <span className="font-mono text-sky-300/80 text-xs flex-shrink-0 w-32">
          {node.customer_part_number ?? <span className="text-slate-600">—</span>}
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
        {node.resulting_revision_id !== null && (
          <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
            ECN #{node.resulting_revision_id}
          </span>
        )}
        {!selected.has(node.part_id) && suggested.has(node.part_id) && (() => {
          const chipDisabled = !editable || (node.is_lead && leadPinned)
            || node.resulting_revision_id !== null
          return (
            <button
              onClick={() => !chipDisabled && toggle(node.part_id)}
              disabled={chipDisabled}
              className="px-2 py-0.5 rounded-full text-xs bg-amber-900 text-amber-100 hover:bg-amber-800 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-amber-900"
              title={t('impact.hint')}
            >
              {t('impact.suggested')} +
            </button>
          )
        })()}
      </div>
      {node.children.map(c => renderNode(c, depth + 1))}
    </div>
  )

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-slate-100 font-semibold">{t('impact.title')}</h3>
          <p className="text-slate-400 text-xs">{t('impact.hint')}</p>
        </div>
        <div className="flex items-center gap-2">
          {impactConfirmedAt ? (
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-200">
              ✓ {t('impact.confirmed')} {impactConfirmedByName ?? '—'} · {new Date(impactConfirmedAt).toLocaleString()}
            </span>
          ) : canConfirm ? (
            <button
              onClick={() => confirmImpact.mutate()}
              disabled={confirmImpact.isPending}
              className="px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-semibold disabled:opacity-50"
            >
              {t('impact.confirm')}
            </button>
          ) : (
            <span className="text-amber-300 text-xs" title={t('actions.notYourDepartment')}>
              {t('impact.pending')}
            </span>
          )}
          {editable ? (
            <button
              onClick={() => apply.mutate()}
              disabled={!dirty || apply.isPending}
              className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm disabled:opacity-50"
            >
              {t('impact.apply')}
            </button>
          ) : (
            <span className="text-amber-300 text-xs">{t('impact.locked')}</span>
          )}
        </div>
      </div>
      {/* Roots grouped by controlled-item class, each behind a rule: Articles,
          Dunnage, Material, Tools, EOAT, … The BOM nesting under each root is
          untouched — grouping only orders the top level. */}
      {groupItems(data.tree).map(group => (
        <div key={group.key} className="border-t border-slate-700 first:border-t-0 first:pt-0 pt-2 mt-2">
          <div className="flex items-center gap-2 px-1 py-1 text-xs uppercase tracking-wide text-slate-500">
            <span>{group.label}</span>
            <span className="ml-auto normal-case">{group.items.length}</span>
          </div>
          {group.items.map(n => renderNode(n, 0))}
        </div>
      ))}
    </div>
  )
}

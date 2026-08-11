/**
 * The workbook's per-department checklist: their activity catalog, one row each,
 * off by default. Ticking a row asks what has to be done — the remark only
 * exists once there is something to remark on. Anything the catalog does not
 * cover goes in as a free line, the way the paper form always allowed.
 *
 * Ticked rows are what costing pre-seeds from, so this list is the bridge
 * between "what is affected" and "what it will cost".
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { DepartmentFieldsProps } from './types'

export interface ImpactItem {
  /** Catalog entry, or null for a free line. */
  activity_id: number | null
  label: string
  impacted: boolean
  remark?: string
}

export const impactsOf = (
  value: Record<string, unknown> | null | undefined,
): ImpactItem[] =>
  value && Array.isArray(value.impacts) ? (value.impacts as ImpactItem[]) : []

/** How many areas a submitted assessment says are impacted. */
export function impactedCount(details: Record<string, unknown> | null | undefined): number {
  return impactsOf(details).filter((i) => i.impacted).length
}

export default function ActivityChecklist({
  departmentId, value, onChange,
}: DepartmentFieldsProps & { departmentId: number }) {
  const { data: activities = [] } = useQuery({
    queryKey: ['cm-activities', departmentId],
    queryFn: () => changesApi.referenceActivities(departmentId),
  })
  const [freeLines, setFreeLines] = useState<string[]>([])
  const impacts = impactsOf(value)

  const itemFor = (activityId: number | null, label: string): ImpactItem =>
    impacts.find((i) => (activityId != null
      ? i.activity_id === activityId
      : i.activity_id == null && i.label === label))
      ?? { activity_id: activityId, label, impacted: false }

  const put = (next: ImpactItem) => {
    const rest = impacts.filter((i) => !(next.activity_id != null
      ? i.activity_id === next.activity_id
      : i.activity_id == null && i.label === next.label))
    // Untouched rows carry no weight: only ticked ones are worth sending.
    const kept = [...rest, next].filter((i) => i.impacted || (i.remark ?? '').trim() !== '')
    onChange({ ...value, impacts: kept })
  }

  const row = (activityId: number | null, label: string, key: string) => {
    const item = itemFor(activityId, label)
    return (
      <li key={key} className="py-1">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" data-testid={`check-${key}`}
            checked={item.impacted}
            onChange={(e) => put({ ...item, impacted: e.target.checked })} />
          <span className={item.impacted ? 'text-slate-100' : 'text-slate-400'}>{label}</span>
        </label>
        {item.impacted && (
          <input type="text" data-testid={`check-remark-${key}`}
            value={item.remark ?? ''}
            onChange={(e) => put({ ...item, remark: e.target.value })}
            placeholder={t('check.remarkPlaceholder')} aria-label={t('check.remark')}
            className="mt-1 ml-6 w-[calc(100%-1.5rem)] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
        )}
      </li>
    )
  }

  return (
    <div className="space-y-1">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('check.title')}</p>
      <p className="text-[11px] text-slate-500">{t('check.hint')}</p>
      {activities.length === 0 && freeLines.length === 0 ? (
        <p className="text-xs text-slate-600">{t('check.empty')}</p>
      ) : (
        <ul className="divide-y divide-slate-700/40 rounded border border-slate-700/60 bg-slate-900/30 px-2">
          {activities.map((a) => row(a.id, a.label, String(a.id)))}
          {freeLines.map((label, i) => (
            label.trim() === '' ? (
              <li key={`free-new-${i}`} className="py-1">
                <input type="text" autoFocus data-testid={`check-free-input-${i}`}
                  aria-label={t('check.itemLabel')} placeholder={t('check.itemPlaceholder')}
                  onBlur={(e) => {
                    const v = e.target.value.trim()
                    if (!v) return
                    setFreeLines((f) => f.map((x, j) => (j === i ? v : x)))
                    put({ activity_id: null, label: v, impacted: true })
                  }}
                  className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
              </li>
            ) : row(null, label, `free-${i}`)
          ))}
        </ul>
      )}
      <button type="button" data-testid="check-add-item"
        onClick={() => setFreeLines((f) => [...f, ''])}
        className="text-xs text-sky-300 hover:text-sky-200">
        {t('check.addItem')}
      </button>
    </div>
  )
}
